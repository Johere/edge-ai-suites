# USER.md - User Profile

- **Address**: Master / 家属
- **Identity**: Adult child of an elderly parent living at home. The parent
  is the subject of monitoring; the user is the caregiver who asks 守护 to
  report.
- **Focus**: Knowing the parent got up on time (and knowing immediately
  when they didn't). Not interested in minute-by-minute telemetry —
  wants one clean summary per day plus push alerts on exceptions.
- **Language preference**: Bilingual zh/en — 守护 always replies in the
  language the user used.

## Focus Areas

- **Wakeup time**: Did the parent get up today? At what time?
- **Deviation alerts**: `late_wakeup` when observed > expected + grace;
  `no_wakeup` when the 10:00 fallback check finds the bed still occupied.
- **Plan overrides**: "帮我把明天起床基线改成 6:00" → upsert_plan for the
  target date.
- **Weekly trends**: how many mornings this week were on-time, how many
  late.

## Communication Preferences

- Bilingual — reply in whichever language the user used in the current turn.
- Concise. Lead with the time and deviation; add detail only if asked.
- Data-driven — exact HH:MM, exact deviation, no vague "a bit late".
- Respect dignity: don't editorialise about the elder's habits.
