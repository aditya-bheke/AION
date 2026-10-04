# 03 — Demo service, dashboard and first live runs

**Date:** 2026-10-04
**Task:** Build the monitored demo service and the dashboard; run the whole system live, as a user would.

## What changed
- `demo/orders-service-history/` — 7 commit overlays (4 fictional developers). Commit 06 makes `get_coupon()` return `None` for unknown/expired coupons while `apply_discount()` still indexes it; commit 07 is an unrelated logging change shipped in the same release. Verified: the existing 9 tests pass at HEAD, while `?coupon=SUMMER23` returns 500 with the expected traceback.
- `demo/demo_repo.py` — builds a real git repo with backdated authors/timestamps and deployment metadata.
- `demo/run_demo.py` — registers the service, records deployments v1.3.0/v1.4.0, runs production, generates traffic (normal → expired coupons after N seconds), includes realistic noise (payment timeouts every 7th checkout, cache-miss warnings).
- `frontend/` — React + Vite dashboard: incident list, incident page (stepper, approval gate, 7 tabs), audit trail, system page. Built and served by FastAPI.

## Tests performed
- `npm run build` — OK.
- **Live run #1** (AION server + demo, real traffic): incident detected → analysed → patched → validated → `awaiting_approval` automatically; deploy before approval returned **409** and production stayed on the buggy commit; approval + deploy executed.
- **Live run #2** after fixes: detection 11:40:47 → awaiting approval 11:40:51 → human approve/deploy 11:41:20 → production redeployed and verified 11:41:22 → `resolved`; `SUMMER23` now returns 200.
- Headless Edge screenshots of the incident list and incident page against live data to check rendering.
- Full test suite after each fix: 33 passed.
- **Final live run** on the final code from a fresh workspace: exactly one incident, resolved, no re-detection during 40 s of continued traffic; then a `--fresh` rebuild against the existing database investigated a new incident correctly.

## Problems encountered and solutions
1. **Production did not reload after deployment.** The demo first ran production with `uvicorn --reload`. After AION's fast-forward merge, the process kept serving the old commit. AION's verification step caught it correctly (`deploy_failed: Production did not come up on the new commit within 45s`) instead of reporting success. Additionally, stopping the reloader on Windows left an **orphaned worker process** still listening on port 8101.
   → Replaced `--reload` with an explicit **GitOps controller** in `run_demo.py` (`ProductionRuntime`): runs uvicorn without the reloader (single process, clean termination) and restarts it when `main` moves. Verified: deploy → `[controller] production branch moved … redeploying` → verified → resolved; port freed on shutdown.
2. **Correlation scores saturated.** An older commit ("Add coupon support") tied the real culprit at 1.0 because blame signals were *summed across stack frames*. → Each signal now counts once per commit (strongest instance), and commits already live in an earlier deployment while the error didn't occur are multiplied by 0.5 ("stable code"). Live ranking became 1.0 / 0.4 / 0.3 / 0.15. Test extended (`older.score < 0.5 < top.score`).
3. **A resolved incident was re-detected.** Error lines logged just before the fix went live were collected after incident #1 closed; no open incident existed, so they opened incident #2, whose revert then failed (already reverted). → The detector now ignores events older than the last closure of an incident with the same signature; a genuine recurrence after closure still opens a new (regression) incident. Test added (`test_late_lines_after_resolution_do_not_reopen_but_regression_does`).

4. **Rebuilding the demo crashed correlation.** `run_demo.py --fresh` creates new commit SHAs while AION's database keeps the old deployment records; `git log old..new` would fail. The same happens in real life after a history rewrite. → `correlate()` ignores deployment records whose commit isn't in the repository (`GitRepo.has_commit`) and records a note in the evidence pack. Verified live: "Ignored 3 deployment record(s)…", correct ranking, and the previous incident was retrieved as `INC-1` (similar past incident). Test extended.

## Status
MVP workflow verified live end-to-end in heuristic mode; LLM path verified via tests with a scripted provider.

## Next step
Documentation and learning system; final full verification.
