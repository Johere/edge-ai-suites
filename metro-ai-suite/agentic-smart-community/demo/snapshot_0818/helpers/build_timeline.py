#!/usr/bin/env python3
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Turn a timeline EDL into an ffmpeg concat list plus a groundtruth SRT.

Every artifact this script emits comes from the same resolved slot list, so the
SRT can never drift out of sync with the video or playlist it describes. Three
layouts share that expansion:

  rtsp24h   full 24h day, rotated so the first entry is what should be playing
            right now — for `-f concat` RTSP push, nothing lands on disk.
  showcase  every clip once, separated by empty-room filler — a short reel.
  validate  4h with events spread evenly, keeping the day->night light arc.

Artifacts are named ``<id>__<mode>.{ffconcat,srt}`` and the SRT's first cue is a
``[META]`` declaration carrying the timeline id and a hash of the slot list, so
`--check` can tell a stale SRT from a current one.

Usage:
  build_timeline.py --timeline PATH [--mode rtsp24h] [--verify]
  build_timeline.py --timeline PATH --mode validate --out-dir DIR
  build_timeline.py --timeline PATH --mode rtsp24h --at 02:30
  build_timeline.py --timeline PATH --check
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import re
import sys
from dataclasses import dataclass

import yaml

MODES = ("rtsp24h", "showcase", "validate")

# validate mode targets
VALIDATE_HOURS = 4
VALIDATE_EVENTS = 40

# showcase mode: filler slots inserted between consecutive clips
SHOWCASE_GAP_SLOTS = 2

# rtsp24h truncates here so the pusher's relaunch lands in continuous sleep
DEFAULT_RTSP_UNTIL = "04:00"
MIN_PLAYLIST_SLOTS = 20


class ConfigError(Exception):
    """Raised for any problem in the timeline file itself."""


@dataclass(frozen=True)
class Slot:
    """One fixed-length position in a layout."""

    index: int  # position within this layout, 0-based
    clip_id: str
    is_event: bool
    day_slot: int | None = None  # position within the 24h day, when meaningful


# ── timeline parsing ─────────────────────────────────────────────────────────


def parse_hhmm(value: object, where: str) -> int:
    """"HH:MM" -> minutes since midnight."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,2}:\d{2}", value):
        raise ConfigError(f"{where}: expected \"HH:MM\", got {value!r}")
    hours, minutes = (int(part) for part in value.split(":"))
    if hours > 23 or minutes > 59:
        raise ConfigError(f"{where}: not a valid time of day: {value!r}")
    return hours * 60 + minutes


def load_timeline(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}

    for key in ("id", "clips_dir", "clips", "schedule", "filler"):
        if not cfg.get(key):
            raise ConfigError(f"missing required key: {key}")

    if not re.fullmatch(r"[A-Za-z0-9._-]+", str(cfg["id"])):
        raise ConfigError(f"id must be filename-safe, got {cfg['id']!r}")

    cfg["clip_seconds"] = int(cfg.get("clip_seconds", 15))
    if 86400 % cfg["clip_seconds"]:
        raise ConfigError(
            f"clip_seconds ({cfg['clip_seconds']}) must divide 86400 evenly"
        )

    base = os.path.dirname(os.path.abspath(path))
    cfg["_clips_root"] = os.path.normpath(os.path.join(base, cfg["clips_dir"]))
    cfg["_source_path"] = os.path.abspath(path)
    return cfg


def resolve_clip_paths(cfg: dict, needed: set[str]) -> dict[str, str]:
    """Map clip ID -> absolute file, failing loudly on anything missing."""
    root = cfg["_clips_root"]
    paths: dict[str, str] = {}
    missing: list[str] = []
    for clip_id in sorted(needed):
        candidate = os.path.join(root, f"{clip_id}.mp4")
        if os.path.isfile(candidate):
            paths[clip_id] = candidate
        else:
            missing.append(f"{clip_id} -> {candidate}")
    if missing:
        raise ConfigError(
            "clip file(s) not found (run normalize_clips_for_concat.sh first):\n  "
            + "\n  ".join(missing)
        )
    return paths


# ── schedule expansion ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Block:
    at_minutes: int
    start_slot: int
    end_slot: int  # exclusive, may exceed slots_per_day when the block wraps
    filler_key: str
    events: tuple[str, ...]
    label: str

    @property
    def length(self) -> int:
        return self.end_slot - self.start_slot


def build_blocks(cfg: dict) -> list[Block]:
    slots_per_day = 86400 // cfg["clip_seconds"]
    slots_per_minute = slots_per_day / 1440

    blocks: list[Block] = []
    for position, raw in enumerate(cfg["schedule"]):
        where = f"schedule[{position}]"
        at_minutes = parse_hhmm(raw.get("at"), f"{where}.at")
        until_minutes = parse_hhmm(raw.get("until"), f"{where}.until")

        start_slot = int(round(at_minutes * slots_per_minute))
        end_slot = int(round(until_minutes * slots_per_minute))
        if end_slot <= start_slot:  # wraps past midnight
            end_slot += slots_per_day

        filler_key = raw.get("filler", "day")
        if filler_key not in cfg["filler"]:
            raise ConfigError(
                f"{where}.filler={filler_key!r} is not a key of `filler:` "
                f"({sorted(cfg['filler'])})"
            )

        events = tuple(raw.get("events") or ())
        unknown = [clip for clip in events if clip not in cfg["clips"]]
        if unknown:
            raise ConfigError(f"{where}.events references unknown clip(s): {unknown}")
        if len(events) > end_slot - start_slot:
            raise ConfigError(
                f"{where}: {len(events)} events do not fit in "
                f"{end_slot - start_slot} slots"
            )

        blocks.append(
            Block(
                at_minutes=at_minutes,
                start_slot=start_slot,
                end_slot=end_slot,
                filler_key=filler_key,
                events=events,
                label=f"{raw['at']}-{raw['until']}",
            )
        )

    # Blocks must tile the day exactly once — a gap would leave dead slots and an
    # overlap would make two blocks fight over the same slot.
    ordered = sorted(blocks, key=lambda block: block.start_slot)
    covered = sum(block.length for block in ordered)
    if covered != slots_per_day:
        raise ConfigError(
            f"schedule covers {covered} slots but a day has {slots_per_day} — "
            "blocks must tile 24h exactly (check for gaps or overlaps)"
        )
    for current, following in zip(ordered, ordered[1:]):
        if current.end_slot != following.start_slot:
            raise ConfigError(
                f"schedule blocks {current.label} and {following.label} are not "
                f"contiguous (slot {current.end_slot} vs {following.start_slot})"
            )
    if ordered[-1].end_slot % slots_per_day != ordered[0].start_slot:
        raise ConfigError(
            f"schedule does not wrap: last block ends at slot "
            f"{ordered[-1].end_slot % slots_per_day}, first starts at "
            f"{ordered[0].start_slot}"
        )
    return blocks


def spread_positions(count: int, span: int) -> list[int]:
    """Evenly distributed offsets for `count` items across `span` slots."""
    if count <= 0:
        return []
    return [int((index + 0.5) * span / count) for index in range(count)]


def apply_after_filler(cfg: dict, day: list[str], is_event: list[bool]) -> None:
    """Let an event hand the filler over to a different room state.

    Without this the room contradicts itself: after `night_out_of_room` the block
    filler would keep showing the resident asleep in bed, and after the lights-out
    clip it would keep showing a bright empty room.

    A clip declares `after_filler: <filler key>` to say what the room looks like
    once it has happened, and that state **persists until another event changes
    it** — daylight does not end just because the next event happens to be
    "reading a book". So every event that really does change the room (getting up,
    going to bed, leaving, coming back) has to declare its own hand-off.

    The day is circular, so the state entering the walk is resolved first.
    """
    slots_per_day = len(day)
    event_indices = [index for index, flag in enumerate(is_event) if flag]
    if not event_indices:
        return

    def handoff(clip_id: str) -> str | None:
        key = cfg["clips"].get(clip_id, {}).get("after_filler")
        if key is None:
            return None
        if key not in cfg["filler"]:
            raise ConfigError(
                f"clips.{clip_id}.after_filler={key!r} is not a key of "
                f"`filler:` ({sorted(cfg['filler'])})"
            )
        return cfg["filler"][key]

    # Incoming state = the last hand-off of the day, since the day loops.
    override: str | None = None
    for index in reversed(event_indices):
        override = handoff(day[index])
        if override is not None:
            break

    start = event_indices[0]
    for step in range(slots_per_day):
        index = (start + step) % slots_per_day
        if is_event[index]:
            declared = handoff(day[index])
            if declared is not None:
                override = declared
        elif override is not None:
            day[index] = override


def expand_day(cfg: dict) -> list[Slot]:
    """The canonical 24h slot list, indexed so slot 0 is 00:00:00 local."""
    slots_per_day = 86400 // cfg["clip_seconds"]
    day: list[str | None] = [None] * slots_per_day
    is_event = [False] * slots_per_day

    for block in build_blocks(cfg):
        filler_clip = cfg["filler"][block.filler_key]
        offsets = spread_positions(len(block.events), block.length)
        placed = {
            offset: clip for offset, clip in zip(offsets, block.events)
        }
        for offset in range(block.length):
            slot_index = (block.start_slot + offset) % slots_per_day
            clip = placed.get(offset)
            day[slot_index] = clip if clip else filler_clip
            is_event[slot_index] = clip is not None

    unfilled = [index for index, clip in enumerate(day) if clip is None]
    if unfilled:  # build_blocks should have caught this already
        raise ConfigError(f"{len(unfilled)} slot(s) left unfilled, first={unfilled[0]}")

    apply_after_filler(cfg, day, is_event)

    return [
        Slot(index=index, clip_id=clip, is_event=is_event[index], day_slot=index)
        for index, clip in enumerate(day)
    ]


# ── clip phase (day vs night) ────────────────────────────────────────────────


def clip_phases(cfg: dict) -> dict[str, str]:
    """Classify each clip as day or night, inferred from the schedule itself.

    Avoids a second source of truth: an event clip's phase is whichever filler
    bucket its schedule block uses, and the filler clips classify themselves.
    """
    filler = cfg["filler"]
    phases: dict[str, str] = {}
    if "day" in filler:
        phases[filler["day"]] = "day"
    for key in ("night", "sleep"):
        if key in filler:
            phases.setdefault(filler[key], "night")

    for raw in cfg["schedule"]:
        phase = "day" if raw.get("filler", "day") == "day" else "night"
        for clip in raw.get("events") or ():
            phases.setdefault(clip, phase)

    for clip in cfg["clips"]:
        phases.setdefault(clip, "day")
    return phases


def filler_for_phase(cfg: dict, phase: str) -> str:
    if phase == "day":
        return cfg["filler"]["day"]
    # Night prefers the sleeping resident over an empty room: an empty bedroom at
    # night would read as "the resident is missing".
    return cfg["filler"].get("sleep") or cfg["filler"]["night"]


# ── layouts ──────────────────────────────────────────────────────────────────


def layout_rtsp24h(cfg: dict) -> list[Slot]:
    return expand_day(cfg)


def layout_showcase(cfg: dict) -> list[Slot]:
    """Every clip once, separated by phase-appropriate filler."""
    phases = clip_phases(cfg)
    filler_ids = set(cfg["filler"].values())

    # Narrative order: walk the schedule as written, then append any clip that is
    # only ever used as filler so the reel really shows all of them.
    ordered: list[str] = []
    for raw in cfg["schedule"]:
        for clip in raw.get("events") or ():
            if clip not in ordered:
                ordered.append(clip)
    for clip in cfg["clips"]:
        if clip not in ordered and clip in filler_ids:
            ordered.append(clip)

    def append_gap(phase: str) -> None:
        gap_clip = filler_for_phase(cfg, phase)
        for _ in range(SHOWCASE_GAP_SLOTS):
            slots.append(Slot(len(slots), gap_clip, False))

    # Lead in and out with filler: it reads like real footage, and it keeps the
    # first event cue from overlapping the [META] cue at 00:00.
    slots: list[Slot] = []
    for clip in ordered:
        append_gap(phases.get(clip, "day"))
        slots.append(Slot(len(slots), clip, True))
    append_gap(phases.get(ordered[-1], "day") if ordered else "day")
    return slots


def layout_validate(cfg: dict) -> list[Slot]:
    """4h with events spread evenly, preserving the day->night light arc."""
    total_slots = VALIDATE_HOURS * 3600 // cfg["clip_seconds"]

    # Narrative order = schedule order as authored, which runs morning -> pre-dawn.
    catalogue: list[tuple[str, str]] = []
    for raw in cfg["schedule"]:
        phase = "day" if raw.get("filler", "day") == "day" else "night"
        for clip in raw.get("events") or ():
            catalogue.append((clip, phase))
    if not catalogue:
        raise ConfigError("schedule declares no events, nothing to validate")

    # Sample up to VALIDATE_EVENTS from the day, cycling if the day has fewer.
    picks: list[tuple[str, str]] = [
        catalogue[index % len(catalogue)]
        for index in spread_positions(
            VALIDATE_EVENTS, max(VALIDATE_EVENTS, len(catalogue))
        )
    ]
    picks = picks[:VALIDATE_EVENTS]

    positions = spread_positions(len(picks), total_slots)
    placed = {position: pick for position, pick in zip(positions, picks)}

    # Each filler slot inherits the phase of the nearest upcoming event, so the
    # lighting changes with the narrative rather than flipping at random.
    phase_at: list[str] = []
    current = placed[min(placed)][1] if placed else "day"
    for index in range(total_slots):
        if index in placed:
            current = placed[index][1]
        phase_at.append(current)

    slots: list[Slot] = []
    for index in range(total_slots):
        if index in placed:
            slots.append(Slot(index, placed[index][0], True))
        else:
            slots.append(Slot(index, filler_for_phase(cfg, phase_at[index]), False))
    return slots


LAYOUTS = {
    "rtsp24h": layout_rtsp24h,
    "showcase": layout_showcase,
    "validate": layout_validate,
}


# ── hashing / identity ───────────────────────────────────────────────────────


# Clip fields that reach a generated artifact: tag/desc land in SRT cue text, the
# rest are what seed_elder_care_history.py writes to the database. Any edit to one
# of these must invalidate the hash, or a stale SRT would look current.
HASHED_CLIP_FIELDS = ("tag", "desc", "event", "severity", "subject")


def slots_sha1(cfg: dict, mode: str, slots: list[Slot]) -> str:
    """Hash everything that shapes an artifact, so staleness is detectable.

    Covers the canonical (unrotated) slot list plus the semantics of every clip it
    references. Purely advisory keys such as `max_events_per_hour` are excluded on
    purpose: changing a validation threshold does not make an existing SRT wrong.
    """
    used_clips = sorted({slot.clip_id for slot in slots})
    semantics = ";".join(
        clip_id
        + "="
        + ",".join(
            f"{field}:{cfg['clips'].get(clip_id, {}).get(field, '')}"
            for field in HASHED_CLIP_FIELDS
        )
        for clip_id in used_clips
    )
    payload = "|".join(
        [
            str(cfg["id"]),
            mode,
            str(cfg["clip_seconds"]),
            ",".join(
                f"{slot.index}:{slot.clip_id}:{'E' if slot.is_event else 'F'}"
                for slot in slots
            ),
            semantics,
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


META_RE = re.compile(r"slots_sha1=([0-9a-f]{40})")


def read_srt_hash(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            head = handle.read(2048)
    except OSError:
        return None
    match = META_RE.search(head)
    return match.group(1) if match else None


# ── output writers ───────────────────────────────────────────────────────────


def rotate(slots: list[Slot], offset: int) -> list[Slot]:
    if not offset:
        return slots
    offset %= len(slots)
    return slots[offset:] + slots[:offset]


def write_concat(path: str, slots: list[Slot], paths: dict[str, str], header: str) -> None:
    lines = ["ffconcat version 1.0", f"# {header}"]
    for slot in slots:
        # Single-quoted paths with embedded quotes escaped, per concat demuxer rules.
        escaped = paths[slot.clip_id].replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


@dataclass
class Cue:
    start_slot: int
    slot_count: int
    clip_id: str


def merge_event_cues(slots: list[Slot]) -> list[Cue]:
    """One cue per event run; consecutive identical clips collapse into one."""
    cues: list[Cue] = []
    for slot in slots:
        if not slot.is_event:
            continue
        if (
            cues
            and cues[-1].clip_id == slot.clip_id
            and cues[-1].start_slot + cues[-1].slot_count == slot.index
        ):
            cues[-1].slot_count += 1
        else:
            cues.append(Cue(slot.index, 1, slot.clip_id))
    return cues


def write_srt(
    path: str,
    cfg: dict,
    mode: str,
    slots: list[Slot],
    digest: str,
    generated: str,
) -> int:
    clip_seconds = cfg["clip_seconds"]
    cues = merge_event_cues(slots)

    blocks: list[str] = []
    meta = (
        f"[META] timeline_id={cfg['id']} mode={mode} slots={len(slots)} "
        f"events={len(cues)} clip_seconds={clip_seconds} "
        f"slots_sha1={digest} generated={generated}"
    )
    blocks.append(
        "1\n"
        f"{srt_timestamp(0)} --> {srt_timestamp(2)}\n"
        f"{meta}"
    )

    for number, cue in enumerate(cues, start=2):
        info = cfg["clips"][cue.clip_id]
        start = cue.start_slot * clip_seconds
        end = start + cue.slot_count * clip_seconds
        text = f"#{cue.start_slot:04d} [{info.get('tag', cue.clip_id)}] {info['desc']}"
        if cue.slot_count > 1:
            text += f" ({cue.slot_count} continuous clips)"
        blocks.append(
            f"{number}\n"
            f"{srt_timestamp(start)} --> {srt_timestamp(end)}\n"
            f"{text}"
        )

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n\n".join(blocks) + "\n")
    return len(cues)


# ── reporting ────────────────────────────────────────────────────────────────


def report_verify(cfg: dict, mode: str, slots: list[Slot], digest: str) -> int:
    """Print the event budget and return the number of budget breaches.

    Everything reported here is countable: rows per event type and observed
    seconds. Nothing depends on the model producing a number.
    """
    clip_seconds = cfg["clip_seconds"]
    slots_per_hour = 3600 // clip_seconds
    budget = int(cfg.get("max_events_per_hour", 0) or 0)

    print(f"timeline : {cfg['id']}  ({cfg.get('description', '')})")
    print(f"mode     : {mode}")
    print(
        f"slots    : {len(slots)} x {clip_seconds}s = "
        f"{len(slots) * clip_seconds / 3600:.2f}h"
    )

    hours: dict[int, list[Slot]] = {}
    for slot in slots:
        hours.setdefault(slot.index // slots_per_hour, []).append(slot)

    print()
    print("  hour   events  clips")
    breaches = 0
    total_events = 0
    for hour in sorted(hours):
        events = [slot for slot in hours[hour] if slot.is_event]
        total_events += len(events)
        breached = bool(budget) and len(events) > budget
        breaches += int(breached)
        detail = ",".join(slot.clip_id for slot in events) or "-"
        flag = "  <-- over budget" if breached else ""
        label = f"{hour:02d}:00" if mode == "rtsp24h" else f"+{hour}h"
        print(f"  {label}  {len(events):6d}  {detail}{flag}")

    print()
    print(f"  total events    : {total_events}")
    print(f"  observed seconds: {total_events * clip_seconds}")
    if budget:
        print(f"  budget          : <= {budget} events/hour", end="")
        print("  OK" if not breaches else f"  BREACHED in {breaches} hour(s)")

    # Per event type — this is what the daily/weekly report counts, so it is the
    # baseline the detected rows get reconciled against.
    by_event: dict[str, int] = {}
    for slot in slots:
        if slot.is_event:
            name = cfg["clips"][slot.clip_id].get("event", "?")
            by_event[name] = by_event.get(name, 0) + 1
    print()
    print("  event rows per day (the number a report should reproduce):")
    for name in sorted(by_event, key=lambda key: (-by_event[key], key)):
        print(f"    {name:20s} {by_event[name]:4d}   {by_event[name] * clip_seconds:5d}s")

    # Room-state walk: which filler is on screen between events. This is where a
    # narrative contradiction shows up — e.g. an empty room while the resident is
    # supposed to be in bed, or night footage after the curtain was opened.
    print()
    print("  room state between events (filler runs):")
    previous: str | None = None
    for slot in slots:
        if not slot.is_event and slot.clip_id != previous:
            label = f"{slot.index * clip_seconds // 3600:02d}:" \
                    f"{slot.index * clip_seconds % 3600 // 60:02d}"
            desc = cfg["clips"].get(slot.clip_id, {}).get("desc", "")
            print(f"    {label}  {slot.clip_id:10s} {desc}")
        previous = slot.clip_id if not slot.is_event else previous

    per_clip: dict[str, int] = {}
    for slot in slots:
        per_clip[slot.clip_id] = per_clip.get(slot.clip_id, 0) + 1
    print()
    print("  slot count per clip:")
    for clip_id in sorted(per_clip):
        kind = "event" if any(
            slot.is_event for slot in slots if slot.clip_id == clip_id
        ) else "filler"
        print(f"    {clip_id:10s} {per_clip[clip_id]:5d}  ({kind})")

    print()
    print(f"  slots_sha1: {digest}")
    return breaches


def window_events(
    cfg: dict, slots: list[Slot], start_hhmm: str, end_hhmm: str
) -> dict[str, int]:
    """Event-type counts inside a wall-clock window."""
    slots_per_minute = (86400 // cfg["clip_seconds"]) / 1440
    start = int(parse_hhmm(start_hhmm, "window start") * slots_per_minute)
    end = int(parse_hhmm(end_hhmm, "window end") * slots_per_minute)
    counts: dict[str, int] = {}
    for slot in slots:
        if slot.is_event and start <= (slot.day_slot or slot.index) < end:
            name = cfg["clips"][slot.clip_id].get("event", "?")
            counts[name] = counts.get(name, 0) + 1
    return counts


# ── main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an ffmpeg concat list and groundtruth SRT from a timeline EDL.",
    )
    parser.add_argument("--timeline", required=True, help="path to the timeline YAML")
    parser.add_argument("--mode", default="rtsp24h", choices=MODES)
    parser.add_argument(
        "--at",
        default="now",
        help='rtsp24h start point: "now" (default) or "HH:MM" local time',
    )
    parser.add_argument(
        "--until",
        default=DEFAULT_RTSP_UNTIL,
        help=f"rtsp24h truncation point (default {DEFAULT_RTSP_UNTIL}); "
        '"none" for a full 24h playlist',
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="where to write artifacts (default: <timeline_dir>/<id>_composed)",
    )
    parser.add_argument(
        "--verify", action="store_true", help="print the event-count budget report"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the existing SRT's hash against the timeline and exit non-zero if stale",
    )
    parser.add_argument(
        "--print-playlist-path",
        action="store_true",
        help="print only the playlist path (for shell wrappers)",
    )
    args = parser.parse_args(argv)

    try:
        cfg = load_timeline(args.timeline)
        slots = LAYOUTS[args.mode](cfg)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    digest = slots_sha1(cfg, args.mode, slots)
    # Default to one directory per timeline so artifacts stay together and
    # --check always looks where the build wrote.
    out_dir = args.out_dir or os.path.join(
        os.path.dirname(cfg["_source_path"]), f"{cfg['id']}_composed"
    )
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, f"{cfg['id']}__{args.mode}")
    srt_path = f"{stem}.srt"
    playlist_path = f"{stem}.ffconcat"

    if args.check:
        existing = read_srt_hash(srt_path)
        if existing is None:
            print(f"stale: no usable SRT at {srt_path}", file=sys.stderr)
            return 1
        if existing != digest:
            print(
                f"stale: {os.path.basename(srt_path)} was built from a different "
                f"timeline\n  srt      : {existing}\n  timeline : {digest}",
                file=sys.stderr,
            )
            return 1
        print(f"current: {os.path.basename(srt_path)} matches {digest}")
        return 0

    try:
        paths = resolve_clip_paths(cfg, {slot.clip_id for slot in slots})
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    # The SRT always describes the canonical, unrotated layout — that keeps it
    # valid no matter which point in the day the playlist starts at.
    generated = dt.datetime.now().replace(microsecond=0).isoformat()
    event_count = write_srt(srt_path, cfg, args.mode, slots, digest, generated)

    playlist_slots = slots
    rotation_note = ""
    if args.mode == "rtsp24h":
        slots_per_day = len(slots)
        slots_per_minute = slots_per_day / 1440
        if args.at == "now":
            now = dt.datetime.now()
            start_slot = int(
                (now.hour * 60 + now.minute + now.second / 60) * slots_per_minute
            ) % slots_per_day
            start_label = now.strftime("%H:%M:%S")
        else:
            start_slot = int(
                parse_hhmm(args.at, "--at") * slots_per_minute
            ) % slots_per_day
            start_label = args.at

        playlist_slots = rotate(slots, start_slot)
        rotation_note = f"start={start_label} (slot {start_slot})"

        if args.until != "none":
            stop_slot = int(
                parse_hhmm(args.until, "--until") * slots_per_minute
            ) % slots_per_day
            length = (stop_slot - start_slot) % slots_per_day
            if length < MIN_PLAYLIST_SLOTS:
                length += slots_per_day  # too close to the cut, run a full lap first
            playlist_slots = playlist_slots[:length]
            rotation_note += f" until={args.until}"

    header = (
        f"{cfg['id']} mode={args.mode} slots={len(playlist_slots)} "
        f"slots_sha1={digest} {rotation_note}".strip()
    )
    write_concat(playlist_path, playlist_slots, paths, header)

    if args.print_playlist_path:
        print(playlist_path)
        return 0

    print(f"timeline_id : {cfg['id']}")
    print(f"mode        : {args.mode}")
    print(f"slots_sha1  : {digest}")
    print(
        f"playlist    : {playlist_path}  "
        f"({len(playlist_slots)} slots, "
        f"{len(playlist_slots) * cfg['clip_seconds'] / 3600:.2f}h"
        + (f", {rotation_note}" if rotation_note else "")
        + ")"
    )
    print(f"srt         : {srt_path}  ({event_count} event cues)")

    if args.verify:
        print()
        breaches = report_verify(cfg, args.mode, slots, digest)
        if args.mode == "rtsp24h":
            counts = window_events(cfg, slots, "14:00", "16:00")
            detail = ", ".join(
                f"{name} x{count}"
                for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            )
            print()
            print(
                f"  14:00-16:00 window: {sum(counts.values())} events "
                f"({detail}), {sum(counts.values()) * cfg['clip_seconds']}s observed"
            )
        if breaches:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
