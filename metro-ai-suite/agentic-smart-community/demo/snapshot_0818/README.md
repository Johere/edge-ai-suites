# 0818 Community-Care Demo (Child Safety + Elder Care)

This guide runs the two-camera community-care demo captured in this snapshot: a child-safety living-room camera and an elder-care bedroom camera, each with its own use case, agent persona and alert rule. The snapshot is a standalone package: it carries demo-specific files and clones the open-source runtime from Edge AI Suites on first deployment.

This demo streams from a **timeline EDL**, so the picture tracks the real clock: the living room is dark and motionless from 21:30 to 06:30, and the elder room's night events land at night.

| Monitor | Use case | Agent | RTSP | Timeline | Alerts fire on |
| --- | --- | --- | --- | --- | --- |
| `cam_child` | `child_safety` | `child-safety-agent` | `rtsp://localhost:8557/live/child` | `helpers/child_safety_timeline.yaml` | any `warn` or `critical` (built-in rule) |
| `cam_elder_care` | `elder_care` | `elder-care-agent` | `rtsp://localhost:8557/live/eldercare` | `helpers/elder_care_timeline.yaml` | only `restlessness` and `night_out_of_room` (`elder_care/evaluate_rules.py`) |

Both cameras publish to the same MediaMTX on `:8557`, which keeps this demo clear of the ready-to-run demo on `:8554`.

## Package and Deploy

Create a portable archive from a source checkout:

```bash
bash demo/snapshot_0818/package.sh /tmp/snapshot_0818.tar.gz
```

On a deployment machine, extract the archive anywhere, enter the extracted directory, and run the deployment entrypoint. It clones the public runtime into `~/edge-ai-suites` when needed, equivalent to:

```bash
git clone https://github.com/open-edge-platform/edge-ai-suites ~/edge-ai-suites
cd ~/edge-ai-suites/metro-ai-suite/agentic-smart-community
```

```bash
tar -xzf snapshot_0818.tar.gz
cd snapshot_0818
bash deploy.sh
```

`deploy.sh` starts the demo after cloning. The other scripts automatically use the same default checkout. Set `EDGE_AI_SUITES_DIR` for another checkout location, `COMPONENT_ROOT` for a nonstandard component path, or `SKIP_START=1` to only clone and validate.

## Prerequisitescd

1. Complete the [Prerequisites](https://github.com/open-edge-platform/edge-ai-suites/blob/main/metro-ai-suite/agentic-smart-community/docs/user-guide/get-started.md#prerequisites) and install [OpenClaw](https://github.com/open-edge-platform/edge-ai-suites/blob/main/metro-ai-suite/agentic-smart-community/docs/user-guide/get-started.md#openclaw).
2. `ffmpeg`, `ffprobe`, `jq`, `curl` and `python3` on `PATH`.
3. MediaMTX at `~/.local/bin/mediamtx` (or set `MEDIAMTX_BIN`).

If a pusher from an earlier session is still holding `:8557`, stop it first — it will have declared only its own RTSP path, and the second camera would be refused. `bash stop-demo.sh --streams` clears it.

## Step 1 - Provide the clip libraries

Clip files are user-provided: `demo/.gitignore` excludes every `*.mp4`, so a fresh clone has none. Export the directory holding each camera's raw clips.

```bash
export SMART_COMMUNITY_DEMO_CHILD_CLIPS=/absolute/path/child_safety_snippets
export SMART_COMMUNITY_DEMO_ELDER_CLIPS=/absolute/path/elder_care_snippets
```

Both default to the directories under `helpers/` in this snapshot. A camera whose directory is missing or holds no MP4s is reported and skipped; the other one still starts.

The expected clip names are listed in [Appendix B](#appendix-b---timelines-and-clip-preparation).

## Step 2 - Start the demo

From the extracted snapshot directory:

```bash
bash start-demo.sh
```

This one-shot launcher normalizes both clip libraries, builds and verifies both timelines, starts the shared RTSP server and one pusher per camera, stages the elder-care alert rule, writes the demo config and the matching monitor subset into `$SMART_COMMUNITY_DATA_DIR`, brings the stack up with `setup_docker.sh --light` (reusing an already-warm `vllm-ipex-serving`), and registers both video-summary task prompts.

It is safe to run again. Clip normalization skips up-to-date outputs, so a warm rerun takes seconds rather than the ~45 s of a cold one. `config.yaml` and `monitors.yaml` are only rewritten when their content changes, and the previous version is kept as `<filename>.YYYYMMDD-HHMMSS.bak`. Files under `demo/` are never modified.

Verify:

```bash
cat demo/snapshot_0818/.run/active-streams.txt
cat "${SMART_COMMUNITY_DATA_DIR:-$HOME/.mcp-smart-community}/monitors.yaml"
ffprobe -rtsp_transport tcp rtsp://localhost:8557/live/child
ffprobe -rtsp_transport tcp rtsp://localhost:8557/live/eldercare
curl -fsS http://localhost:3101/health
docker logs -f docker-smart-community-mcp-server-1
```

Open `http://localhost:3100/` to confirm both monitors appear and each starts an RTSP live preview when selected.

## Step 3 - Seed the history

Without this the demo can only answer questions about today. "How many times this week", "compare with the same period last week" and the weekly reports all need days that do not exist unless the stream ran for a week.

```bash
bash helpers/seed_demo_history.sh            # dry run, prints the plan
bash helpers/seed_demo_history.sh --commit   # insert mock data for the previous 7 days
```
> Note: use `bash helpers/seed_demo_history.sh --commit --days N ` to specify N days

Seven previous complete calendar days are written per camera, at the same density as the live stream so today never reads as an outlier:

| Camera | Rows/day (oldest → newest) | Alerts/day |
| --- | --- | --- |
| `cam_child` | 117 → 150 | 14 → 30 |
| `cam_elder_care` | 143 → 169 | 2 → 5 |

Reruns are idempotent: seeded rows are tagged `seed://<use_case>/dayN`, and the default `--purge` removes exactly those before reinserting. Every value is derived from the date, so a purge-and-reseed reproduces byte-identical rows.

`--reset` is **destructive**: it drops every `events` / `video_summary_tasks` / `alerts` / `reports` row for both demo monitors, real ones included. Use it to clear a polluted history — for example data recorded before this snapshot's timeline existed, when the child camera looped a one-hour file and produced six danger alerts every hour around the clock. Left in place, those rows dominate any weekly comparison and make daily reports claim the evening and small hours are the risky part of the day.

Seeded rows carry `seed://…` in `event_file_path` rather than a real file, so the dashboard cannot play a clip for them. Live rows are unaffected.

How the seeded days are constructed — the ramp, and the four mechanisms that make each day differ — is in [Appendix C](#appendix-c---how-the-seeded-history-is-built).

## Step 4 - Enable proactive OpenClaw alerts

Optional, and only needed for agents to push alerts into a chat session. Interactive MCP tool calls work without it. The snapshot installer builds and links the adapter, registers both agents, adds the two monitor routes, installs their personas and shared skills, validates the configuration, and restarts the gateway.

```bash
bash openclaw-adapter/install.sh
```

It derives the model for newly created agents from `agents.defaults.model.primary`. Set `AGENT_MODEL` when that default is not configured, `MCP_URL` to use a non-default MCP endpoint, or `SKIP_RESTART=1` when the gateway must not be restarted during installation.

```bash
AGENT_MODEL=vllm-local/Qwen/Qwen3.6-35B-A3B \
  bash openclaw-adapter/install.sh
```

The installer is idempotent: it does not replace existing monitor routes, agent definitions, skills, or persona files. Open the Control UI at `http://localhost:18789` with `openclaw dashboard`.

## Step 5 - Scheduled reports

```bash
openclaw cron add --name child-safety-daily-22 --cron "30 22 * * *" --tz Asia/Shanghai \
  --agent child-safety-agent --session "session:daily_report" \
  --session-key agent:child-safety-agent:daily_report \
  --no-deliver --message "Generate today's child-safety daily report."

openclaw cron add --name elder-care-daily-22 --cron "0 22 * * *" --tz Asia/Shanghai \
  --agent elder-care-agent --session "session:daily_report" \
  --session-key agent:elder-care-agent:daily_report \
  --no-deliver --message "Generate today's elder-care daily report for cam_elder_care."
```

Use `openclaw cron list` and `openclaw cron rm <job-id>` to review or remove them.

## Step 6 - Talk with the agents

The seeded week is what makes the trend questions answerable. Both agents are bilingual.

**Child Safety agent** (`cam_child`)

- 本周有几次危险行为？ / How many risky events this week?
- 今天和上周同期比怎么样？ / How does today compare with the same period last week?
- 生成今天的儿童安全日报。 / Generate today's child-safety report.
- 孩子现在安全吗？ / Is the child safe right now?
- 客厅还有哪些地方需要做安全改造？ / What would make this room safer?

**Elder Care agent** (`cam_elder_care`)

- 老人这周几点起床？ / What time did Dad get up this week?
- 今天有没有躁动不安？ / Any restlessness today?
- 这周有几次夜间离室？ / How many night out-of-room events this week?
- 生成今天的老人照护日报。 / Generate today's elder-care report.
- 今天有什么异常吗？ / Anything unusual today?

Follow up naturally — "why did you flag that", "which day was worst", "check the current scene again".

## Step 7 - Stop the demo

```bash
bash stop-demo.sh            # pushers, RTSP server, app tier
bash stop-demo.sh --streams  # pushers and RTSP server only
```

`vllm-ipex-serving` is left running so its multi-minute recompile is not repaid. `bash setup_docker.sh --down` tears down everything.

## Appendix A - Wall-clock alignment and rehearsal

The pushers are started without `--at`, so `timeline_to_rtsp.sh` defaults to `now`: it rotates the playlist to whatever should be on screen at this moment, and re-anchors to the clock on every relaunch, so `-re` drift is discarded rather than accumulated. That is why the child camera is genuinely quiet overnight.

The chain only holds if the container agrees with the host about local time. `docker/set_env.sh` forwards the host timezone into the MCP container so SQLite's `datetime('now','localtime')` — used for every `created_at` — matches the wall clock the timeline is aligned to. `start-demo.sh` sources it; running the pieces by hand without it mixes local-time seeded rows and UTC live rows in one table, an offset that is nearly invisible in a report.

To rehearse without waiting for the right hour, run a pusher by hand and jump into a busy window:

```bash
bash helpers/timeline_to_rtsp.sh \
  --timeline helpers/child_safety_timeline.yaml \
  --url rtsp://localhost:8557/live/child --at 15:00
```

Good windows: child `15:00-17:00` (three window-sill climbs, two scissors) and `18:00-20:00` (both lighter events); elder `14:00-16:00` (the four restlessness observations) and `02:00-04:00` (out of bed, leaves the room, returns).

`--speed N` fast-forwards for inspecting an EDL. Never use it to generate data — the timestamps stop meaning anything.

## Appendix B - Timelines and clip preparation

Both timelines author **10 observations per waking hour**, which is the budget `max_events_per_hour` asserts. `build_timeline.py --verify` prints the per-hour table, the per-event row counts a report should reproduce, and a room-state walk showing which filler is on screen between events — the walk is where a narrative contradiction shows up, such as a bright empty room after lights-out.

```bash
cd demo/snapshot_0818/helpers
python3 build_timeline.py --timeline child_safety_timeline.yaml --mode rtsp24h --verify
python3 build_timeline.py --timeline elder_care_timeline.yaml   --mode rtsp24h --verify
python3 build_timeline.py --timeline child_safety_timeline.yaml --check   # is the committed SRT stale?
```

**`child_safety_day_v1`** — 150 events/day = 120 `normal` + 12 `jump` + 9 `climb` + 4 `knife` + 3 `fall` + 2 `fire`. Awake 06:30-21:30; the remaining nine hours are a dark, motionless living room that produces no motion trigger, no VLM work and no alerts. Safe observations are 80% of the day, which is what a normal living room looks like; the 30 danger events average two per waking hour, so with `alerts.cooldown_seconds: 60` an alert lands roughly every half hour.

`prepare_child_clips.sh` stages the ten clips `child_safety_snippets/compose_demo.sh` uses under timeline IDs, synthesizes the two filler clips from `child-care-bg.png`, and normalizes everything to `1280x720 @ 30fps`, 10 s per clip.

| ID | Source clip | event | severity |
| --- | --- | --- | --- |
| `A1_normal` | `child-care-003-reading` | `normal` | info |
| `A2_normal` | `child-care-003-eating-candidate` | `normal` | info |
| `A3_normal` | `child-care-003-safe-playing` | `normal` | info |
| `J1_jump` | `child-care-003-jump` | `jump` | warn |
| `F1_fall` | `child-care-003-falldown` | `fall` | critical |
| `K1_knife` | `child-care-003-scissors` | `knife` | critical |
| `R1_fire` | `child-care-003-fire` | `fire` | critical |
| `C1_climb` `C2_climb` `C3_climb` | `child-care-003-climb-window`, `_2`, `_3` | `climb` | critical |
| `E1_empty` `E2_empty` | generated from `child-care-bg.png` | `normal` | info |

Clip seconds is 10, not the elder library's 15, because `-frames:v` only truncates: a 15 s target against a 10.05 s source emits 300 frames instead of 450, and normalization's own concat-compatibility assert fails. 10 also divides 86400 evenly.

A clip ID may contain exactly **one** underscore. `clip_id_of` in `normalize_clips_for_concat.sh` matches `^[A-Za-z0-9]+_([A-Za-z0-9]+)_`, so `A1_normal.mp4` falls through to the whole-basename branch, which is what we want, while `A1_normal_reading.mp4` would collapse to the ID `normal` and make all three `A` clips collide.

**`elder_care_day_v2`** — 169 events/day = 164 info + 5 warn. Two changes from v1:

- Waking hours 06:00-22:00 now carry 10 observations each. Only **state** events were densified (`in_bed`, `in_room_activity`, `sit_up_in_bed`) — a camera reporting "sitting in the armchair" every six minutes is what the real pipeline produces. **Transition and alert** events are unchanged in count: getting up ten times an hour has no meaning, and the four afternoon `restlessness` observations are this use case's headline statistic.
- `T1` (curtain drawn, lights off) moved from the 16:00-18:00 block to the end of the 18:00-22:00 block, landing near 21:57. In v1 its `after_filler: sleep` made everything after 18:00 night-time, leaving no room for a 16-hour waking window.

The `id` was bumped v1 → v2 because the slot hash necessarily changed while `demo/user-case-register/elder_care_timeline.yaml` still holds the v1 content under the v1 id. Sharing an id across differing content would make each SRT look stale to the other's `--check`.

The launcher always writes normalized clips into `helpers/<library>/normalized/` regardless of where the sources came from, because each timeline's `clips_dir` resolves relative to the timeline file. Your clip directory can therefore be read-only. Set `FORCE=1` to re-encode unconditionally.

## Appendix C - How the seeded history is built

`seed_history.py` expands the same EDL the stream plays and writes only the event slots — filler is motion-gated away in the real pipeline, so seeding it would make history denser than reality. Each row is written three ways so every consumer sees it:

- `events` and `video_summary_tasks`, with the extension columns and their order taken from `use_case_dict[<use_case>].schema.video_summary_tasks.extensions`. Order matters: `summary_text` is assembled the way the server's `normalizeSummaryTextBySchema` does, and elder-care's report reads `summary_text` in preference to `desc`.
- `alerts`, decided exactly the way the server decides: the use case's `evaluate_rules_path` when it has one, otherwise `severity >= warn`. Written with `notified=1`, because reports over `alerts` filter on that by default.

Descriptions come from the timeline's `desc_zh`, most of them lifted verbatim from observed live rows, so a report never mixes English seeded text with Chinese live text.

Row counts follow absolute per-class targets rather than a density fraction, since history runs at the same density as the live stream. Info rows stay nearly flat; the danger count carries the trend, because that is what the reports and the "how many times this week" questions ask about. Row count, observed seconds and the danger total are therefore monotonic across the six days.

Everything else varies, keyed off the date so a purge-and-reseed is byte-identical:

1. **Weekday/weekend arc** — a weighted time profile that pushes weekend mornings back and favours the late morning. Its reach is limited by arithmetic and honestly so: at 88-100% info retention the highest-target days drop almost nothing and a weekend looks like a weekday.
2. **Order rotation** — rotates the ranked candidate list before taking the target count, so one day drops `fire` and keeps `knife` while the next does the reverse. Counts are untouched.
3. **Clip rotation** — among clips sharing an `(event, severity)`, a different one each day, so a week of `climb` rows shows all three descriptions instead of one repeated six times.
4. **Time jitter** — ±20 minutes (doubled on weekends), always **clamped to the event's own schedule block**, including when resolving a collision. That clamp is what keeps the quiet window quiet: a 21:00 event can drift later but never past its block into the night.

## Appendix D - Event vocabulary and alert rules

**`child_safety`** — extension columns `severity, event, desc`. Vocabulary (see `demo/prompts/child_safety_monitor.txt`): `fall`, `choking`, `drowning`, `climb`, `near_stove`, `run`, `knife`, `fire`, `jump`, `outlet`, `normal`. No `evaluate_rules_path`, so the built-in rule fires an alert on any `warn` or `critical`.

**`elder_care`** — extension columns `severity, event, desc, subject`. Vocabulary (see `elder_care/prompt.md`): `in_bed`, `sit_up_in_bed`, `out_of_bed`, `in_room_activity`, `return_to_bed`, `restlessness`, `night_out_of_room`, `staff_enter`, `staff_leave`, `staff_visit`, `room_empty`, `uncertain`. `critical` is forbidden by contract. `elder_care/evaluate_rules.py` narrows alerts to `restlessness` and `night_out_of_room` only; everything else is recorded as an info-level timeline entry with no alert row.

`alerts.description` is formatted `[<useCase>] <alertType>: <severity> — <desc>`, with elder-care appending ` (subject=…)`.

## Appendix E - Known gaps

**`fall` is not detected.** The `falldown` clip has never produced `event: fall`. Across 292 completed `cam_child` tasks from the pre-timeline run, not one description mentions falling. The timeline still declares `F1_fall` as `fall`/`critical` because that is the ground truth; the groundtruth SRT is what makes the miss measurable. Compare a run against `helpers/child_safety_day_v1_composed/child_safety_day_v1__rtsp24h.srt`, whose cues carry the slot index and the expected label.

**Elder `return_to_bed` is rarely recognized.** `N6` was consistently classified `in_room_activity` in the observed data.

**Report `data_source` falls back to `alerts` for every monitor.** `/api/reports/generate` and the `generate_report` MCP tool both derive the table from `use_case_dict[...].reports.data_source`, but in the running server that lookup yields nothing and the `?? "alerts"` fallback always wins. Observed on all four registered monitors, including `cam_fridge` (configured `events`) and `cam_elder_bedroom` (configured `video_summary_tasks`), and it survives a container restart. Consequence for this demo: an elder-care daily report summarizes the 2-5 alerts of the day instead of the ~169 observations. The MCP tool accepts an explicit override, so ask the agent for the report with `data_source: video_summary_tasks`, or call:

```bash
curl -s -X POST http://localhost:3100/api/reports/generate \
  -H 'Content-Type: application/json' \
  -d '{"monitor_id":"cam_elder_care","type":"custom","period_start":"2026-08-19 00:00:00","period_end":"2026-08-19 23:59:59"}'
```

and note the `dataSource` field in the response to confirm which table was actually read. This is a pre-existing server issue, not specific to this snapshot.

**`type` and an explicit period are mutually exclusive.** `period_start` / `period_end` are honoured only for `type: "custom"`; `daily`, `weekly` and `monthly` always compute their own window ending today.

## Appendix F - Files in this snapshot

| Path | Purpose |
| --- | --- |
| `start-demo.sh` / `stop-demo.sh` | One-shot launcher and teardown |
| `config.demo.yaml` | Runtime config, including both use-case declarations |
| `monitors.demo.yaml` | Both monitors, filtered by the launcher to the active streams |
| `elder_care/prompt.md` | Elder-care VLM task prompt |
| `elder_care/evaluate_rules.py` | Elder-care alert rule, staged into `$SMART_COMMUNITY_DATA_DIR/use-cases/` |
| `agents/` | `child-safety-agent` and `elder-care-agent` personas |
| `helpers/child_safety_timeline.yaml` | Child-safety EDL |
| `helpers/elder_care_timeline.yaml` | Elder-care EDL |
| `helpers/build_timeline.py` | EDL → RTSP playlist + groundtruth SRT |
| `helpers/timeline_to_rtsp.sh` | Wall-clock-aligned RTSP pusher |
| `helpers/normalize_clips_for_concat.sh` | One concat-safe encode profile, with a compatibility assert |
| `helpers/child_safety_snippets/prepare_child_clips.sh` | Stage, synthesize filler, normalize |
| `helpers/mediamtx.demo.yml` | Shared RTSP server, both paths on `:8557` |
| `helpers/start_rtsp_server.sh` | Idempotent start/stop for that server |
| `helpers/seed_history.py` | History seeder |
| `helpers/seed_demo_history.sh` | Seeds both cameras with their own targets |
| `helpers/prompt_md_to_task.py` | `## SECTION` prompt markdown → anchored task format |
| `note.md` | Historical pointer to the portable deployment workflow |
