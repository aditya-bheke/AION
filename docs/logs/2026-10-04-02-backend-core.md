# 02 — Backend core

**Date:** 2026-10-04
**Task:** Implement the complete backend workflow.

## What changed
| Component | Files | Summary |
|---|---|---|
| Config / DB / models | `config.py`, `db.py`, `models.py` | env-based settings; SQLite in WAL mode; 11 tables, one per workflow stage |
| State machine + audit | `lifecycle.py`, `audit.py` | 12 statuses, explicit transition table, every transition audited |
| Log pipeline | `logs/normalize.py`, `ingest.py`, `detector.py`, `collector.py` | templating + fingerprints, signature table, spike-vs-baseline detection, file-tail collector |
| Git | `gitops/repo.py`, `correlation.py` | CLI wrapper; blame-at-deployed-revision correlation with reasons |
| AI | `ai/providers/*`, `context.py`, `rca.py`, `patcher.py` | provider protocol (Anthropic SDK, OpenAI-compatible), strict JSON schemas, repair turn, evidence pack, grounding, heuristic analyzer |
| Remediation | `remediation/service.py`, `apply.py`, `policy.py` | worktree + branch per attempt; search/replace edits; code-enforced policy; revert strategy |
| Validation | `validation/runner.py` | syntax, fail-to-pass, tests, staging process, replay |
| Deployment | `deploy/deployer.py` | preflight checks, ff-only merge, production verification |
| Orchestration | `pipeline/worker.py`, `orchestrator.py` | single worker thread; staged pipeline with bounded repair loop; deploy job |
| API | `api/*.py`, `schemas.py`, `main.py` | REST endpoints, 409 for illegal transitions, lifespan, restart recovery, serving the dashboard |

## Tests performed
`backend/tests/` — 28 unit tests first (normalisation, detection, correlation on a real built repo, patch policy, lifecycle invariant, grounding, schema/repair logic), then 3 end-to-end tests that build the demo repo, run the real service to produce logs, and drive the full workflow through the API (heuristic path to `resolved`; LLM path with a scripted test double including fail-to-pass regression test and HTTP 400 replay; a broken patch that never reaches approval). All passed.

An inspection run printed the actual evidence prompt, RCA and validation output to check quality, not just assertions.

## Problems encountered and solutions
1. **Huge stack traces in the prompt.** FastAPI/Starlette/anyio frames made ~90 % of the trace. → `compact_stack_trace()` keeps application frames and collapses library frames ("… 25 framework/library frame(s) omitted …"). Test added.
2. **Python strings written through shell heredocs** turned `"\n"` into a real newline twice, producing syntax errors → caught by the test run/`ast.parse`; fixed with direct file edits. (Lesson: edit Python source with the editor tool, not via shell-escaped scripts.)
3. **Anthropic SDK version.** pip resolved `anthropic` 1.x (uses `httpx2`); checked the signatures of `beta.messages.create` (`output_config`, `fallbacks`, `thinking`) in the installed package before writing the adapter, and kept our own `httpx` usage separate from the SDK.

## Status
Backend functionally complete; 32 tests passing.

## Next step
Dashboard and live end-to-end demo.
