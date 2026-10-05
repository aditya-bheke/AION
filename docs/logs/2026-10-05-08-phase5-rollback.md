# 08 — Phase 5 (part 1): rollback

**Date:** 2026-10-05
**Task:** Make AION deployments reversible: manual rollback by an approver and automatic rollback when post-deploy verification fails.

## What changed
- `lifecycle.py`: states `rolling_back`, `rolled_back`; `resolved → rolling_back`, `deploy_failed → rolling_back`, `rolling_back → rolled_back | error`, `rolled_back → analyzing | rejected`; `rolled_back` is open and re-runnable.
- `deploy/deployer.py`: `wait_for_commit()` extracted; `rollback()` = preflight + `git revert --no-edit <fix>` + Deployment `rollback-incident-<id>` + running-commit verification.
- `pipeline/orchestrator.py`: `run_rollback()`; `run_deploy()` triggers an automatic rollback when the merge happened but verification failed (`AION_AUTO_ROLLBACK`).
- API `POST /api/incidents/{id}/rollback` (approver, comment); worker `enqueue_rollback`; restart recovery maps `rolling_back → error`.
- Dashboard: "Roll back this fix" (with confirmation) on resolved incidents, rolling-back/rolled-back panels, stepper and badges.

## Tests
79 passing: manual rollback (viewer 403; tree equals the pre-fix tree; revert commit kept in history; rollback deployment by `human:aditya`; re-run allowed afterwards); automatic rollback on simulated failed verification (`deploy_failed → rolling_back → rolled_back`, actor `system:auto-rollback`); updated state-machine invariants.

Live (scratch database, real production process under the GitOps controller): approve + deploy → production on fix `d9d4ca5`, `SUMMER23` → 200; rollback → production on revert `2643fe8` (by `human:riya`), `SUMMER23` → 500 again, as expected after undoing the fix.

## Problems encountered
- A variable used to decide on automatic rollback was only assigned on the failure path, which would have crashed every successful deployment — caught in review before running, fixed.
- An old test asserted `resolved` was terminal; updated to the new, intended rule (resolved → rolling_back only).

## Next step
Phase 5 part 2: GitHub pull requests for validated fixes + GitHub Actions checks (needs a GitHub repo and token).
