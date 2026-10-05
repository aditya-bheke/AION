# 10 — Phase 6: notifications and insights

**Date:** 2026-10-05
**Task:** Tell people when AION needs them, and measure incident response.

## What changed
- `notify.py`: outbox notifier thread reading the audit trail after a stored cursor; Slack/Discord/generic payloads; delivery log; transport injection for tests.
- Models `NotificationChannel` (encrypted URL), `NotificationDelivery`, `NotifierCursor`; `api/notifications.py` (admin CRUD, test send, deliveries); `AION_PUBLIC_URL`.
- `api/insights.py`: per-incident MTTD / time to fix / decision / deploy / MTTR from timestamps + audit trail; outcome counts.
- Dashboard: Insights page (KPI cards, per-incident table), Notifications card (channels, events, test, delivery log).

## Tests
86 passing. `test_ops.py`: URL encrypted and hidden, admin-only, invalid events rejected; first start sets the cursor without flooding; detected/awaiting-approval/resolved notifications reach the subscribed channel with incident links, nothing sent twice, a broken webhook is logged while others still deliver; insights from a real run.

**Live** (scratch database, real notifier thread, local webhook receiver standing in for Slack): received *test → 🚨 new incident → 🔒 fix ready → ✅ deployed* in order with links; deliveries logged as sent; Insights: MTTD 9.5 s, time to validated fix 4.4 s, deploy 2.4 s, MTTR 16.8 s.

## Notes
- The live test ran AION with GitHub disabled (`AION_GITHUB_REPO=` override) so it would not open another real PR.

## Status
Phase 6 complete.
