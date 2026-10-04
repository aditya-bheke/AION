# AION — Project Status

_Last updated: 2026-10-04_

## Current state
**MVP: functional and verified end-to-end.** The complete workflow — log collection → detection → deduplication → git/deployment correlation → root-cause analysis → candidate patch → automated validation (tests + staging + traffic replay) → human approval → production deployment → production verification → audit — runs live against a real demo service and is covered by automated tests.

| | |
|---|---|
| Backend tests | 44 passing (`cd backend; .venv\Scripts\python -m pytest -q`, ~30 s) |
| Live demo | verified: incident detected → awaiting approval in ~4 s; approve + deploy → verified + resolved in ~2 s |
| AI mode on this machine | local LLM: Ollama + qwen2.5-coder:7b (on D:), via `backend/.env`; start it with `scripts\start-ollama.ps1` |
| Evaluation (4 scenarios) | heuristic: 4/4 reach approval gate, RCA 3/3 · local LLM: 3/4, RCA 2/3 (AI patches fail validation; revert fallback rescues 2) — `docs/EVALUATION.md` |
| Dashboard | built (`frontend/dist`), served at http://127.0.0.1:8000 |

## Completed
- Log ingestion: file-tail collector + HTTP ingest API; JSON log normalisation; stack-frame parsing.
- Deduplication: template masking + error fingerprints; signature table with counts/first/last seen.
- Detection: per-signature spike vs baseline; incident-level dedup; no re-detection from late lines after closure.
- Git correlation: blame at the deployed revision, function ranges via `ast`, deployment window, explainable scores.
- AI layer: provider protocol; Anthropic (official SDK, structured outputs) and OpenAI-compatible adapters; evidence pack with IDs; RCA schema separating observations/inferences; grounding checks; deterministic fallback.
- Remediation: isolated worktree/branch per attempt; LLM search/replace edits + regression test, or `git revert`; code-enforced patch policy; bounded repair loop.
- Validation: syntax, fail-to-pass regression check, unit tests, staging process, replay of failing and baseline requests.
- Human approval gate: state machine, approval bound to commit SHA, separate deploy action, reject/withdraw.
- Deployment: preflight checks, fast-forward merge, verification of running commit + replay on production.
- Audit trail; React dashboard; demo service + GitOps controller; documentation system.
- Phase 2: local LLM (portable Ollama on D:), 4 bug scenarios, evaluation harness + results, dependency-overlap correlation signal, indentation-only edit repair, revert fallback after failed AI patches.

## Currently being worked on
Nothing in progress. **Phase 2 (real AI + evaluation) is complete** — see `docs/EVALUATION.md`. Next suggested: compare with Claude, then Phase 3 (authentication, sandboxed validation, secret redaction).

## Known bugs
- None open. Four bugs found during live testing were fixed (see `docs/logs/2026-10-04-03-…`).

## Known limitations
- No authentication: anyone who can reach the API can approve (server binds to 127.0.0.1).
- AI-generated code runs on the host during validation (separate process, timeouts) — no container sandbox.
- Python stack traces only; logs-only detection with fixed thresholds; hand-tuned correlation weights.
- Staging/production are local processes; replay covers GET/HEAD requests only.
- Single worker thread; SQLite; no schema migrations (delete `workspace/aion.db` after model changes).
- No automatic rollback.
- Logs may contain sensitive data and are included in prompts when an external LLM is configured.
Full list: `docs/ROADMAP.md`.

## Important technical decisions (summary — full reasoning in `docs/DECISIONS.md`)
Modular monolith (FastAPI + SQLite/SQLAlchemy + React/Vite) · in-process single worker · structured JSON logs · regex templating + stack fingerprints · spike-vs-baseline detection · git CLI · blame-based explainable correlation · provider-neutral LLM layer, Claude by default · evidence pack instead of vector RAG · evidence IDs + grounding · deterministic fallback, clearly labelled · search/replace patches · code-enforced patch policy · worktree per attempt · local CI runner with staging replay · approval as a state-machine gate bound to a SHA · GitOps fast-forward deployment with verification · append-only audit.

## What remains
0. (Optional) Run the evaluation with Claude for a stronger-model comparison.
1. Authentication and approver roles (optionally two-person approval).
2. Container sandbox for validation; secret/PII redaction before prompting.
3. Real CI integration (GitHub Actions) and PR-based fixes.
4. Rollback (manual one-click, then automatic on failed verification); canary deployments.
5. Metrics-based detection; more languages (Java, Node.js).
6. Vector retrieval over runbooks/postmortems; learned correlation weights.
7. Evaluation suite of seeded bugs (RCA accuracy, patch success per model).
8. Repeated evaluation runs per scenario (LLM variance); more scenarios.

## How to run the current version
```powershell
# one-time
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# terminal 1
cd backend; .venv\Scripts\python -m aion          # dashboard: http://127.0.0.1:8000

# terminal 2
backend\.venv\Scripts\python demo\run_demo.py --fresh
```
Optional AI: edit `backend\.env` (`ANTHROPIC_API_KEY=…`, or `AION_OPENAI_BASE_URL` + `AION_OPENAI_MODEL` for LM Studio/Ollama) and restart AION. Step-by-step demo script: `docs/DEMO.md`.
