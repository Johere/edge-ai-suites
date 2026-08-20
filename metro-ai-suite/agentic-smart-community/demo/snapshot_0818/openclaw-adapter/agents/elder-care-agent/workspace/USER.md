# USER.md — User Profile

- **Address**: Master / 监护人
- **Identity**: Family member or professional caregiver of a single elderly resident living alone in their bedroom.
- **Focus**: Knowing — without being spammed — when the resident shows clinical signals that warrant a check-in (restlessness, night-time leaving the room). All other behaviour is a queryable timeline, not a push.
- **Language**: bilingual zh/en.

## Focus areas

- **Real-time clinical signals**: `restlessness` (反复坐起 / 持续踱步) and `night_out_of_room` (夜间离开房间). Both are warn-level alerts that should reach them immediately.
- **On-demand check**: wants to see what's happening *right now* in the room without paging through hours of footage.
- **Daily timeline**: wants a short wrap-up of the day's behaviour — when the resident was in bed, sat up, got up, walked, was visited by staff, was alone in the room, was uncertain. Frequencies and durations accumulated downstream.
- **Staff visits**: visibility into when care staff actually entered/left the room — useful for shift audits.

## Communication preferences

- Wants exact facts — event name, time, subject (resident / staff / none).
- Wants the **opposite** of alarmism. The pipeline already filters out non-clinical events; the agent must not re-escalate them.
- Wants `uncertain` events reported as such — never silently treated as a baseline.
- No made-up counts or minute figures.