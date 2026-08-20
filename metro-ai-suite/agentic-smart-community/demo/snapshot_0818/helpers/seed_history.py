#!/usr/bin/env python3
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Backfill previous days of observations so trends have a baseline.

A 1:1 timeline needs a real day to produce a day of data, so a weekly trend would
need a week of streaming. This script writes the earlier days straight into
`smart-community.db` from the same EDL the stream plays, leaving today to be
produced for real by the live pipeline. Every seeded day is drawn from the
timeline's own `clips:` semantics, so the seeded history and the live day agree on
what an event means.

Generalized from demo/user-case-register/seed_elder_care_history.py. What is new:

  * Use-case agnostic. The extension columns to write, and their order, come from
    `use_case_dict[<use_case>].schema.video_summary_tasks.extensions` in the
    runtime config rather than being hardcoded. Order matters: `summary_text` is
    assembled the way normalizeSummaryTextBySchema does it, and elder-care's daily
    report reads `summary_text` (buildTasksSrt prefers it over `desc`), so a
    wrong order shows up as `(no summary)` in the report.

  * Alerts. Each seeded task is run through the same alert decision the server
    makes — the use case's `evaluate_rules_path` when it has one, otherwise
    `severity >= warn` — and a matching `alerts` row is written with notified=1.
    Child-safety's daily report reads the `alerts` table, and both agents'
    alert_query tools read it, so without this the seeded week is invisible.

  * Absolute per-class targets instead of a density fraction. The timelines now
    author ~10 observations per waking hour, and history should sit at the same
    density, so the ramp is expressed as row counts (see --calm-targets).

  * Per-day variation. Six days thinned from one fixed slot list are six
    identical days. Four deterministic mechanisms make each day differ — see
    "per-day variation" below.

Only event slots are seeded. Filler slots are motion-gated away in the real
pipeline, so inserting them would make the history denser than reality.

Rows are tagged in `video_summary_tasks.summary_clip_input` with a
`seed://<use_case>/dayN` prefix, which makes `--purge` exact and reruns idempotent.

Run this AFTER registering the use case: the extension columns only exist once
registration has applied the schema extension.

Usage:
  seed_history.py --monitor cam_child --use-case child_safety \
      --timeline child_safety_timeline.yaml                       # dry run
  seed_history.py --monitor cam_child --use-case child_safety \
      --timeline child_safety_timeline.yaml --commit
  seed_history.py --monitor cam_child --use-case child_safety --purge-only --commit
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import subprocess
import sys

import yaml

DATA_DIR = os.environ.get(
    "SMART_COMMUNITY_DATA_DIR", os.path.expanduser("~/.mcp-smart-community")
)
DEFAULT_DB = os.path.join(DATA_DIR, "smart-community.db")
DEFAULT_CONFIG = os.path.join(DATA_DIR, "config.yaml")
SEED_SCHEME = "seed://"

# Observed VLM latency between a clip ending and its alert landing.
ALERT_LATENCY_SECONDS = 8

# Absolute row targets per class, oldest seeded day first. Info observations stay
# nearly flat (the camera looks at the room just as often every day); the danger
# count is what carries the weekly trend, because that is what the reports and the
# "how many times this week" questions actually ask about.
DEFAULT_TARGETS_CALM = (106, 110, 113, 116, 118, 120)
DEFAULT_TARGETS_DANGER = (17, 20, 23, 26, 28, 30)

# ── per-day variation ────────────────────────────────────────────────────────
# Governing rule: the shape varies, the per-class counts do not. Row count,
# observed seconds and the danger total therefore stay monotonic across the ramp,
# which is what makes "more than the same period last week" literally true. Which
# events, which clip, and at what minute are all free to move.
#
# Every mechanism is keyed off date.toordinal() — no `random` — so a --purge and
# rerun reproduces byte-identical rows.
#
# 1. Weekday/weekend arc (ARC_PROFILES below).
# 2. Order rotation: rotate the ranked candidate list before taking the target
#    count, so one day drops `fire` and keeps `knife` while the next does the
#    reverse. Counts are untouched because we still take exactly N.
# 3. Clip rotation: among clips sharing an (event, severity), pick a different one
#    each day, so a week of rows does not repeat one sentence six times.
# 4. Time jitter, clamped to the event's own schedule block.
#
# Weighted time windows applied before thinning: a window's weight divides the
# rank, so weight > 1 pulls those events forward (more likely to survive) and
# weight < 1 pushes them back (first to be dropped).
#
# No weight is ever zero and the windows cover the full day. Excluding a window
# outright shrinks the candidate pool, and when the pool falls below the target
# the day silently under-delivers — which breaks the exact row counts the whole
# monotonicity argument rests on.
#
# Reach is limited by arithmetic, and honestly so: history runs at the same
# density as the live stream, so retention is 88-100% for info rows. On the
# highest-target days almost nothing is dropped and the weekend looks like a
# weekday. The profile shapes the sparser days; `jitter` (doubled on weekends)
# and the clip rotation are what differentiate the rest.
ARC_PROFILES = {
    # Weekdays: no bias, events land wherever the timeline put them.
    "weekday": (("00:00", "24:00", 1.0),),
    # Weekends: the household gets up late, and the late morning is the busy part.
    "weekend": (
        ("00:00", "09:00", 0.25),
        ("09:00", "12:00", 2.0),
        ("12:00", "24:00", 1.0),
    ),
}

DEFAULT_JITTER_MINUTES = 20
# Weekends are less scheduled, so the same events scatter more in time.
WEEKEND_JITTER_MULTIPLIER = 2

SEVERITY_ORDER = {"info": 0, "warn": 1, "critical": 2}


class SeedError(Exception):
    pass


# ── timeline expansion (mirrors build_timeline.py) ───────────────────────────


def parse_hhmm(value: str) -> int:
    hours, minutes = (int(part) for part in str(value).split(":"))
    return hours * 60 + minutes


class Candidate:
    """One event slot from the timeline, plus the block it may drift inside."""

    __slots__ = ("slot", "clip_id", "block_start", "block_end")

    def __init__(self, slot: int, clip_id: str, block_start: int, block_end: int):
        self.slot = slot
        self.clip_id = clip_id
        self.block_start = block_start
        self.block_end = block_end


def load_events(timeline_path: str) -> tuple[dict, list[Candidate]]:
    """Return (config, event candidates) — event slots only, in day order."""
    with open(timeline_path, encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    for key in ("id", "clips", "schedule"):
        if not cfg.get(key):
            raise SeedError(f"timeline missing required key: {key}")

    clip_seconds = int(cfg.get("clip_seconds", 15))
    slots_per_day = 86400 // clip_seconds
    slots_per_minute = slots_per_day / 1440

    candidates: list[Candidate] = []
    for position, block in enumerate(cfg["schedule"]):
        start = int(round(parse_hhmm(block["at"]) * slots_per_minute))
        end = int(round(parse_hhmm(block["until"]) * slots_per_minute))
        if end <= start:
            end += slots_per_day
        span = end - start
        clips = list(block.get("events") or ())
        for index, clip_id in enumerate(clips):
            if clip_id not in cfg["clips"]:
                raise SeedError(
                    f"schedule[{position}] references unknown clip {clip_id!r}"
                )
            offset = int((index + 0.5) * span / len(clips))
            candidates.append(
                Candidate((start + offset) % slots_per_day, clip_id, start, end)
            )

    candidates.sort(key=lambda c: c.slot)
    cfg["_clip_seconds"] = clip_seconds
    cfg["_slots_per_day"] = slots_per_day
    return cfg, candidates


GOLDEN_RATIO_CONJUGATE = 0.6180339887498949


def selection_ranks(count: int) -> list[float]:
    """Rank per index such that any low-rank prefix spreads across the whole day.

    Ranking by the fractional part of i*phi is a low-discrepancy sequence, so the
    lowest-ranked k entries are evenly scattered rather than clustered in the
    morning.
    """
    order = sorted(range(count), key=lambda i: (i * GOLDEN_RATIO_CONJUGATE) % 1.0)
    ranks = [0.0] * count
    for position, index in enumerate(order):
        ranks[index] = float(position)
    return ranks


def arc_weight(cfg: dict, slot: int, profile: tuple) -> float:
    """Weight for a slot under an arc profile; 0 means excluded."""
    slots_per_minute = cfg["_slots_per_day"] / 1440
    for start_hhmm, end_hhmm, weight in profile:
        start = int(parse_hhmm(start_hhmm) * slots_per_minute)
        end = int(parse_hhmm(end_hhmm) * slots_per_minute)
        if start <= slot < end:
            return float(weight)
    return 0.0


def take(
    cfg: dict,
    candidates: list[Candidate],
    target: int,
    profile: tuple,
    rotation: int,
) -> list[Candidate]:
    """Pick `target` candidates: arc-weighted ranking, rotated for variety."""
    if not candidates or target <= 0:
        return []

    ranks = selection_ranks(len(candidates))
    keyed: list[tuple[float, int, Candidate]] = []
    for index, candidate in enumerate(candidates):
        weight = arc_weight(cfg, candidate.slot, profile)
        if weight <= 0:
            continue
        keyed.append((ranks[index] / weight, index, candidate))

    if not keyed:
        return []
    keyed.sort(key=lambda item: (item[0], item[1]))

    if target > len(keyed):
        # Silently returning fewer rows would break the monotonic row counts the
        # weekly comparisons rely on, so say so instead.
        print(
            f"  warning: target {target} exceeds {len(keyed)} available candidate(s) "
            "— capping (check the target lists against the timeline)",
            file=sys.stderr,
        )

    # Rotating the ranked list keeps the count exact while changing WHICH
    # candidates survive, so consecutive days differ in composition.
    offset = rotation % len(keyed)
    rotated = keyed[offset:] + keyed[:offset]
    chosen = [item[2] for item in rotated[: min(target, len(rotated))]]
    chosen.sort(key=lambda c: c.slot)
    return chosen


def clip_groups(cfg: dict, clip_ids: set[str]) -> dict[tuple[str, str], list[str]]:
    """Interchangeable clips, grouped by (event, severity), derived from the EDL."""
    groups: dict[tuple[str, str], list[str]] = {}
    for clip_id in sorted(clip_ids):
        info = cfg["clips"][clip_id]
        key = (info.get("event", ""), info.get("severity", "info"))
        groups.setdefault(key, []).append(clip_id)
    return groups


def jitter_slots(cfg: dict, day: dt.date, chosen: list[Candidate], minutes: int) -> None:
    """Nudge each event in time, clamped to its own schedule block.

    Clamping is what keeps the quiet window quiet: a 21:00 event can drift later
    but never past its block into the night, so "nothing between lights-out and
    dawn" survives the jitter.
    """
    if minutes <= 0:
        return
    slots_per_minute = cfg["_slots_per_day"] / 1440
    span = int(minutes * slots_per_minute)
    if span <= 0:
        return

    slots_per_day = cfg["_slots_per_day"]
    # Two observations at the same second would be an artifact of the jitter, not
    # something the pipeline can produce, so collisions are resolved to the
    # nearest free slot — but only ever WITHIN the block. Nudging past the block
    # bound is what would leak an event into the quiet window.
    used: set[int] = set()

    for index, candidate in enumerate(chosen):
        digest = hashlib.sha1(f"{day.isoformat()}:{index}".encode()).digest()
        delta = int.from_bytes(digest[:4], "big") % (2 * span + 1) - span
        low = candidate.block_start
        high = candidate.block_end - 1
        # Blocks that wrap midnight were expanded past slots_per_day; compare in
        # that same unwrapped space, then fold back.
        slot = candidate.slot
        if slot < low:
            slot += slots_per_day
        target = max(low, min(high, slot + delta))

        chosen_slot = None
        for offset in range(high - low + 1):
            for probe in (target + offset, target - offset):
                if low <= probe <= high and probe % slots_per_day not in used:
                    chosen_slot = probe
                    break
            if chosen_slot is not None:
                break
        if chosen_slot is None:  # block fully occupied — keep the clamped slot
            chosen_slot = target

        candidate.slot = chosen_slot % slots_per_day
        used.add(candidate.slot)

    chosen.sort(key=lambda c: c.slot)


# ── use case config ─────────────────────────────────────────────────────────


def load_use_case(config_path: str, use_case: str) -> dict:
    """Extension columns (in declaration order) and the alert rule override."""
    with open(config_path, encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    entry = (cfg.get("use_case_dict") or {}).get(use_case)
    if entry is None:
        raise SeedError(
            f"use case {use_case!r} is not declared in {config_path}.\n"
            "Register the use case first — seeding before registration would "
            "write rows the schema cannot describe."
        )
    extensions = (
        ((entry.get("schema") or {}).get("video_summary_tasks") or {}).get("extensions")
        or []
    )
    evaluate_rules_path = entry.get("evaluate_rules_path")
    return {
        "columns": [ext["name"] for ext in extensions],
        "evaluate_rules_path": (
            os.path.expanduser(evaluate_rules_path) if evaluate_rules_path else None
        ),
        "report_source": (entry.get("reports") or {}).get("data_source"),
    }


def format_alert_message(
    use_case: str, alert_type: str, severity: str, desc: str, extra: str = ""
) -> str:
    """Mirror of packages/tools/src/rule-engine/alert-message.ts formatAlertMessage."""
    body = f"[{use_case}] {alert_type}: {severity} — {desc}"
    return f"{body} ({extra})" if extra else body


class AlertDecider:
    """Resolve alerts exactly the way the task-poller does, with memoization.

    Distinct field combinations number in the dozens while rows number in the
    thousands, so the override subprocess is called once per combination.
    """

    def __init__(self, use_case: str, override_path: str | None):
        self.use_case = use_case
        self.override_path = override_path
        self._cache: dict[str, str | None] = {}
        if override_path and not os.path.isfile(override_path):
            raise SeedError(
                f"configured evaluate_rules_path does not exist: {override_path}"
            )

    def describe(self) -> str:
        return self.override_path or "defaultRuleEvaluator (severity >= warn)"

    def decide(self, fields: dict[str, str]) -> str | None:
        key = json.dumps(fields, sort_keys=True, ensure_ascii=False)
        if key not in self._cache:
            self._cache[key] = (
                self._via_override(key) if self.override_path else self._default(fields)
            )
        return self._cache[key]

    def _default(self, fields: dict[str, str]) -> str | None:
        severity = (fields.get("severity") or "").lower()
        level = SEVERITY_ORDER.get(severity)
        if level is None or level < SEVERITY_ORDER["warn"]:
            return None
        return format_alert_message(
            self.use_case,
            fields.get("event") or "alert",
            severity,
            fields.get("desc") or fields.get("description") or "",
        )

    def _via_override(self, fields_json: str) -> str | None:
        result = subprocess.run(
            ["python3", "-S", self.override_path, fields_json],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SeedError(
                f"evaluate_rules_path failed ({result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        # Contract: the JSON is the LAST non-empty stdout line; earlier lines are
        # free for the script's own debugging.
        lines = [line.strip() for line in result.stdout.split("\n") if line.strip()]
        payload = json.loads(lines[-1]) if lines else None
        if not payload:
            return None
        return format_alert_message(
            self.use_case,
            payload.get("alertType") or "alert",
            (payload.get("severity") or "warn").lower(),
            payload.get("description") or "",
        )


# ── database ────────────────────────────────────────────────────────────────


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def preflight(conn: sqlite3.Connection, monitor_id: str, columns: list[str]) -> None:
    row = conn.execute(
        "SELECT use_case FROM monitors WHERE id = ?", (monitor_id,)
    ).fetchone()
    if row is None:
        raise SeedError(
            f"monitor {monitor_id!r} is not registered.\n"
            "Register the use case and bind the stream first — seeding before "
            "registration would write rows the schema cannot describe."
        )

    present = table_columns(conn, "video_summary_tasks")
    missing = [name for name in columns if name not in present]
    if missing:
        raise SeedError(
            "video_summary_tasks is missing column(s): "
            + ", ".join(missing)
            + "\nThese are added when the use case is registered with the extended "
            "schema. Register first, then seed."
        )


def seed_tag(use_case: str, day_offset: int) -> str:
    return f"{SEED_SCHEME}{use_case}/day{day_offset}"


def build_rows(
    cfg: dict,
    chosen: list[Candidate],
    monitor_id: str,
    use_case: str,
    day_offset: int,
    day: dt.date,
    columns: list[str],
    decider: AlertDecider,
) -> list[dict]:
    clip_seconds = cfg["_clip_seconds"]
    tag = seed_tag(use_case, day_offset)
    midnight = dt.datetime.combine(day, dt.time())

    rows: list[dict] = []
    for candidate in chosen:
        info = cfg["clips"][candidate.clip_id]
        start = midnight + dt.timedelta(seconds=candidate.slot * clip_seconds)
        end = start + dt.timedelta(seconds=clip_seconds)

        # `desc_zh` is what the live VLM actually emits; `desc` (English) is for
        # the SRT. Seeded rows must read like live rows or a report mixes languages.
        values = {
            "severity": info.get("severity", "info"),
            "event": info.get("event", ""),
            "desc": info.get("desc_zh") or info.get("desc", ""),
            "subject": info.get("subject", ""),
        }
        fields = {name: values.get(name, "") for name in columns}
        # summary_text is assembled the way normalizeSummaryTextBySchema does:
        # one `name: value` line per declared extension, in declaration order.
        summary_text = "\n".join(
            f"{name}: {fields[name]}" for name in columns if fields[name]
        )

        rows.append(
            {
                "monitor_id": monitor_id,
                "start_time": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": end.strftime("%Y-%m-%d %H:%M:%S"),
                "alert_time": (
                    end + dt.timedelta(seconds=ALERT_LATENCY_SECONDS)
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "duration_seconds": float(clip_seconds),
                "clip_input": f"{tag}/{candidate.clip_id}@{candidate.slot:04d}",
                "summary_text": summary_text,
                "fields": fields,
                "event": values["event"],
                "severity": values["severity"],
                "alert_message": decider.decide(fields),
            }
        )
    return rows


def insert_rows(
    conn: sqlite3.Connection, rows: list[dict], columns: list[str], use_case: str
) -> tuple[int, int]:
    """Insert events + video_summary_tasks (+ alerts where the rule fires)."""
    column_sql = "".join(f", {name}" for name in columns)
    placeholders = "".join(", ?" for _ in columns)
    task_sql = (
        "INSERT INTO video_summary_tasks ("
        "monitor_id, event_id, summary_clip_input, summary_text, status, "
        f"completed_at, created_at{column_sql}"
        f") VALUES (?, ?, ?, ?, 'completed', ?, ?{placeholders})"
    )

    tasks = alerts = 0
    for row in rows:
        cursor = conn.execute(
            """
            INSERT INTO events (
                monitor_id, motion_type, start_time, end_time, duration_seconds,
                event_file_path, prefilter_passed, created_at
            ) VALUES (?, 'motion', ?, ?, ?, ?, 1, ?)
            """,
            (
                row["monitor_id"],
                row["start_time"],
                row["end_time"],
                row["duration_seconds"],
                row["clip_input"],
                row["start_time"],
            ),
        )
        event_id = cursor.lastrowid

        cursor = conn.execute(
            task_sql,
            (
                row["monitor_id"],
                event_id,
                row["clip_input"],
                row["summary_text"],
                row["end_time"],
                row["start_time"],
            )
            + tuple(row["fields"][name] for name in columns),
        )
        task_id = cursor.lastrowid
        tasks += 1

        if row["alert_message"]:
            # notified=1 on purpose: reports over `alerts` filter notified=1 by
            # default, so a cooled-down row would be invisible to them.
            conn.execute(
                """
                INSERT INTO alerts (
                    monitor_id, task_id, event_id, use_case, description,
                    notified, created_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    row["monitor_id"],
                    task_id,
                    event_id,
                    use_case,
                    row["alert_message"],
                    row["alert_time"],
                ),
            )
            alerts += 1
    return tasks, alerts


def purge(conn: sqlite3.Connection, monitor_id: str, use_case: str) -> tuple[int, int, int]:
    """Remove previously seeded rows for this monitor, leaving real data alone."""
    prefix = f"{SEED_SCHEME}{use_case}/"
    task_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM video_summary_tasks "
            "WHERE monitor_id = ? AND summary_clip_input LIKE ? || '%'",
            (monitor_id, prefix),
        )
    ]
    alert_count = 0
    if task_ids:
        marks = ",".join("?" for _ in task_ids)
        alert_count = conn.execute(
            f"SELECT COUNT(*) FROM alerts WHERE monitor_id = ? AND task_id IN ({marks})",
            (monitor_id, *task_ids),
        ).fetchone()[0]
        # Alerts first, then tasks, then events — each holds a key into the next.
        conn.execute(
            f"DELETE FROM alerts WHERE monitor_id = ? AND task_id IN ({marks})",
            (monitor_id, *task_ids),
        )
    conn.execute(
        "DELETE FROM video_summary_tasks "
        "WHERE monitor_id = ? AND summary_clip_input LIKE ? || '%'",
        (monitor_id, prefix),
    )
    event_count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE monitor_id = ? AND event_file_path LIKE ? || '%'",
        (monitor_id, prefix),
    ).fetchone()[0]
    conn.execute(
        "DELETE FROM events WHERE monitor_id = ? AND event_file_path LIKE ? || '%'",
        (monitor_id, prefix),
    )
    return event_count, len(task_ids), alert_count


def reset_monitor(conn: sqlite3.Connection, monitor_id: str) -> dict[str, int]:
    """Delete EVERY row for this monitor, seeded or real. Destructive."""
    counts: dict[str, int] = {}
    for table in ("alerts", "video_summary_tasks", "reports", "events"):
        counts[table] = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE monitor_id = ?", (monitor_id,)
        ).fetchone()[0]
        conn.execute(f"DELETE FROM {table} WHERE monitor_id = ?", (monitor_id,))
    return counts


# ── reporting ───────────────────────────────────────────────────────────────


def parse_targets(raw: str | None, default: tuple[int, ...]) -> tuple[int, ...]:
    if not raw:
        return default
    try:
        values = tuple(int(part) for part in raw.replace(" ", "").split(","))
    except ValueError as error:
        raise SeedError(f"invalid target list {raw!r}: {error}") from error
    if not values or any(value < 0 for value in values):
        raise SeedError(f"invalid target list {raw!r}")
    return values


def target_for(targets: tuple[int, ...], position: int) -> int:
    return targets[min(position, len(targets) - 1)]


def summarize(rows: list[dict], label: str) -> None:
    danger = sum(1 for row in rows if row["severity"] != "info")
    alerts = sum(1 for row in rows if row["alert_message"])
    seconds = sum(row["duration_seconds"] for row in rows)
    by_event: dict[str, int] = {}
    for row in rows:
        by_event[row["event"]] = by_event.get(row["event"], 0) + 1
    detail = " ".join(f"{name}={count}" for name, count in sorted(by_event.items()))
    print(
        f"  {label}  rows={len(rows):4d}  danger={danger:3d}  alerts={alerts:3d}  "
        f"observed={seconds:6.0f}s  {detail}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill previous days of observations into smart-community.db.",
    )
    parser.add_argument("--monitor", required=True, help="monitor ID, e.g. cam_child")
    parser.add_argument("--use-case", required=True, help="use case key, e.g. child_safety")
    parser.add_argument("--timeline", help="timeline EDL (required unless --purge-only)")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument(
        "--days",
        type=int,
        default=len(DEFAULT_TARGETS_CALM),
        help=f"how many previous days to seed (default {len(DEFAULT_TARGETS_CALM)}; "
        "today is never touched)",
    )
    parser.add_argument(
        "--calm-targets",
        help="comma-separated info-row counts, oldest day first "
        f"(default {','.join(map(str, DEFAULT_TARGETS_CALM))})",
    )
    parser.add_argument(
        "--danger-targets",
        help="comma-separated warn/critical row counts, oldest day first "
        f"(default {','.join(map(str, DEFAULT_TARGETS_DANGER))})",
    )
    parser.add_argument(
        "--jitter",
        type=int,
        default=DEFAULT_JITTER_MINUTES,
        help=f"+/- minutes of per-event time jitter (default {DEFAULT_JITTER_MINUTES}; "
        "0 disables). Always clamped to the event's schedule block.",
    )
    parser.add_argument(
        "--commit", action="store_true", help="actually write; otherwise print the plan"
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="delete previously seeded rows for this monitor before inserting",
    )
    parser.add_argument(
        "--purge-only", action="store_true", help="purge and exit without inserting"
    )
    parser.add_argument(
        "--reset-monitor",
        action="store_true",
        help="DESTRUCTIVE: delete every events/tasks/alerts/reports row for this "
        "monitor, seeded or real, before inserting",
    )
    args = parser.parse_args(argv)

    if args.days < 1:
        print("error: --days must be at least 1", file=sys.stderr)
        return 2
    if not os.path.isfile(args.db):
        print(f"error: database not found: {args.db}", file=sys.stderr)
        return 2
    if not args.purge_only and not args.timeline:
        print("error: --timeline is required unless --purge-only", file=sys.stderr)
        return 2

    try:
        use_case_cfg = load_use_case(args.config, args.use_case)
        calm_targets = parse_targets(args.calm_targets, DEFAULT_TARGETS_CALM)
        danger_targets = parse_targets(args.danger_targets, DEFAULT_TARGETS_DANGER)
        cfg: dict = {}
        candidates: list[Candidate] = []
        if args.timeline:
            cfg, candidates = load_events(args.timeline)
        decider = AlertDecider(args.use_case, use_case_cfg["evaluate_rules_path"])
    except (SeedError, OSError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    columns = use_case_cfg["columns"]
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        preflight(conn, args.monitor, columns)
    except SeedError as error:
        print(f"error: {error}", file=sys.stderr)
        conn.close()
        return 2

    print(f"database   : {args.db}")
    print(f"monitor    : {args.monitor}   use case: {args.use_case}")
    print(f"columns    : {', '.join(columns)}   (schema declaration order)")
    print(f"alert rule : {decider.describe()}")
    print(f"report src : {use_case_cfg['report_source'] or '(default)'}")
    if cfg:
        print(f"timeline   : {cfg['id']}  ({len(candidates)} event slots/day)")
    print(f"mode       : {'COMMIT' if args.commit else 'DRY RUN (no writes)'}")
    print()

    before = conn.execute(
        "SELECT COUNT(*) FROM video_summary_tasks WHERE monitor_id = ?",
        (args.monitor,),
    ).fetchone()[0]
    print(f"existing video_summary_tasks rows for {args.monitor}: {before}")
    print()

    if args.reset_monitor:
        counts = reset_monitor(conn, args.monitor)
        detail = "  ".join(f"{table}={count}" for table, count in counts.items())
        print(f"reset      : deleting ALL rows for {args.monitor} — {detail}")
        if not args.commit:
            conn.rollback()
        print()
    elif args.purge or args.purge_only:
        events, tasks, alerts = purge(conn, args.monitor, args.use_case)
        print(
            f"purge      : {events} events + {tasks} tasks + {alerts} alerts "
            f"tagged {SEED_SCHEME}{args.use_case}/"
        )
        if not args.commit:
            conn.rollback()
        print()

    if args.purge_only:
        if args.commit:
            conn.commit()
            print("committed purge")
        else:
            print("dry run — nothing deleted; add --commit to apply")
        conn.close()
        return 0

    try:
        groups = clip_groups(cfg, {c.clip_id for c in candidates})
        calm = [
            c for c in candidates if cfg["clips"][c.clip_id].get("severity", "info") == "info"
        ]
        danger = [
            c for c in candidates if cfg["clips"][c.clip_id].get("severity", "info") != "info"
        ]

        today = dt.date.today()
        planned: list[tuple[int, list[dict]]] = []
        print("plan (oldest first; today is left to the live pipeline):")
        # Oldest day first so the ramp reads chronologically.
        for position, day_offset in enumerate(range(args.days, 0, -1)):
            day = today - dt.timedelta(days=day_offset)
            ordinal = day.toordinal()
            profile_name = "weekend" if day.weekday() >= 5 else "weekday"
            profile = ARC_PROFILES[profile_name]

            chosen = take(
                cfg, calm, target_for(calm_targets, position), profile, ordinal
            ) + take(
                cfg, danger, target_for(danger_targets, position), profile, ordinal
            )
            chosen = [Candidate(c.slot, c.clip_id, c.block_start, c.block_end) for c in chosen]
            chosen.sort(key=lambda c: c.slot)

            # Swap in a sibling clip with the same meaning, so descriptions differ
            # from one day to the next.
            for index, candidate in enumerate(chosen):
                info = cfg["clips"][candidate.clip_id]
                group = groups[(info.get("event", ""), info.get("severity", "info"))]
                candidate.clip_id = group[(ordinal + index) % len(group)]

            jitter = args.jitter * (
                WEEKEND_JITTER_MULTIPLIER if profile_name == "weekend" else 1
            )
            jitter_slots(cfg, day, chosen, jitter)

            rows = build_rows(
                cfg, chosen, args.monitor, args.use_case, day_offset,
                day, columns, decider,
            )
            planned.append((day_offset, rows))
            summarize(rows, f"{day.isoformat()} {profile_name:7s} (day-{day_offset})")
    except SeedError as error:
        print(f"error: {error}", file=sys.stderr)
        conn.close()
        return 2

    total = sum(len(rows) for _, rows in planned)
    total_alerts = sum(
        1 for _, rows in planned for row in rows if row["alert_message"]
    )
    print()
    print(
        f"total to insert: {total} events + {total} video_summary_tasks "
        f"+ {total_alerts} alerts"
    )

    if not args.commit:
        print()
        print("dry run — nothing written. Re-run with --commit to apply.")
        conn.rollback()
        conn.close()
        return 0

    tasks = alerts = 0
    for _, rows in planned:
        written_tasks, written_alerts = insert_rows(conn, rows, columns, args.use_case)
        tasks += written_tasks
        alerts += written_alerts
    conn.commit()

    after = conn.execute(
        "SELECT COUNT(*) FROM video_summary_tasks WHERE monitor_id = ?",
        (args.monitor,),
    ).fetchone()[0]
    print()
    print(f"inserted {tasks} event+task pair(s) and {alerts} alert(s)")
    print(f"video_summary_tasks rows for {args.monitor}: {before} -> {after}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
