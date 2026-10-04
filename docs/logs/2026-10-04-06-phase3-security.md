# 06 — Phase 3: security hardening

**Date:** 2026-10-04
**Task:** Close the three biggest security gaps: unauthenticated approvals, AI-written code running on the host, and sensitive data in prompts.

## What changed
| Area | Files | Summary |
|---|---|---|
| Authentication & roles | `security.py`, `api/auth.py`, `cli.py`, `models.py` (User, UserSession), all routers | PBKDF2 (600k) password hashes, opaque session tokens stored as SHA-256, 12 h expiry, logout, lockout after 5 failures, roles viewer < engineer < approver < admin, service token for machine endpoints, admin CLI |
| Human approval | `api/incidents.py`, `deploy/deployer.py` | approver identity from the session; optional two-person rule (`AION_REQUIRED_APPROVALS`), re-checked by the deployer; deployment records who pressed deploy |
| Redaction | `ai/redact.py`, `pipeline/orchestrator.py`, `remediation/service.py` | log/code profiles; stored pack = what the model saw + counts; shown in the dashboard |
| Sandbox | `validation/sandbox.py`, `validation/runner.py`, `sandbox/Dockerfile`, `scripts/build-sandbox.ps1` | `Sandbox` interface; Docker: no network, read-only source + root FS, non-root, no capabilities, resource limits; replay inside the container; fail-closed |
| Dashboard | `pages/Login.jsx`, `auth.js`, `api.js`, `App.jsx`, `ApprovalPanel.jsx`, `SystemPage.jsx`, `IncidentDetail.jsx` | sign-in, user/role in the header, role-aware approval panel, two-person progress, redaction card, security settings card |
| Clients | `demo/run_demo.py`, `evaluation/run_eval.py`, `scripts/setup.ps1` | service token; setup generates one |

## Tests
64 passing, 1 skipped: `test_auth.py` (hashing, token storage, lockout, logout/disabled users, roles, service token, two-person rule, deployer re-check), `test_redact.py`, `test_sandbox.py` (fail-closed, isolation flags; real-container test skipped until the image exists), e2e test proving a customer e-mail in failing requests never reaches the LLM. Evaluation (heuristic) unchanged with security on: 4/4.

Live run (scratch database): anonymous request 401, viewer approve 403, approver approve + deploy → resolved; audit and deployment record `human:riya`.

## Problems encountered
1. **Stale worktree folder blocked a new incident** (found in the live run): a fresh database restarted incident ids at 1, but `workspace/worktrees/.../incident-1-a1` from an earlier session still existed and the rebuilt repo didn't know it, so `git worktree add` failed. → `remove_worktree` deletes untracked stale folders; resolved incidents now clean up their worktrees. Test added.
2. A bulk text replacement in the evaluation script also changed an `import os` inside an embedded script string → harness errors; caught by running the evaluation, fixed.
3. Docker Desktop's disk image is on C: (4.5 GB); per the project rule (D: drive) the sandbox image is built only after moving it to D:.

## Status
Phase 3 implemented. Pending: build `aion-sandbox:py310` and run the real-container test after the Docker disk move.

## Update 2026-10-05: Docker sandbox verified
Built `aion-sandbox:py310` (246 MB; Docker's disk stays on C: — acceptable). Real-container test passes (no network, read-only source). One fix found only in a real container: `cp -a` failed as the non-root user (`preserving times for '/work/.'`) → `cp -r`. Evaluation with `AION_SANDBOX=docker`: 4/4, syntax/tests/staging/replay all inside containers, ~7 s per incident (`evaluation/results/20261005-0026-heuristic.md`).
