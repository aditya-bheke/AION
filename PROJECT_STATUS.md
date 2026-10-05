# AION — Project Status

_Last updated: 2026-10-04_

## Current state
**MVP: functional and verified end-to-end.** The complete workflow — log collection → detection → deduplication → git/deployment correlation → root-cause analysis → candidate patch → automated validation (tests + staging + traffic replay) → human approval → production deployment → production verification → audit — runs live against a real demo service and is covered by automated tests.

| | |
|---|---|
| Backend tests | 83 passing (incl. real Docker sandbox test when Docker Desktop is running) (`cd backend; .venv\Scripts\python -m pytest -q`, ~30 s) |
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
- Phase 5 (part 2): GitHub pull requests for validated fixes, GitHub Actions as an approval/deploy gate, fast-forward deployment to GitHub `main`, demo history pushed to GitHub.
- Phase 5 (part 1): manual and automatic rollback (`rolling_back` / `rolled_back` states, revert commit, runtime verification).
- Phase 4: AI provider chosen in the dashboard with encrypted API keys and presets (Claude, OpenAI, Groq, OpenRouter, Gemini, Ollama, LM Studio, custom); MCP connector (`python -m aion.mcp_server`, agent token, task bridge, no approve/deploy tools); pipeline no longer holds a DB write lock during model calls.
- Phase 3: sign-in with roles (viewer/engineer/approver/admin), PBKDF2 passwords, hashed session tokens, login lockout, service token for machine clients, optional two-person approval, approver identity from the session; secret/PII redaction before prompting; fail-closed Docker sandbox for validation; admin CLI.

## Currently being worked on
**Phase 5 — safer production changes: complete.** (1) Manual and automatic rollback. (2) GitHub: each validated fix becomes a pull request; GitHub Actions on the PR must pass before approval and deployment; deploying fast-forwards GitHub `main` to the validated commit and GitHub marks the PR merged. Both verified live (PR #1 on `aditya-bheke/aion-demo-orders-service`).

**Phase 4 — AI connectivity: complete.** Choose the AI from the dashboard: API-key providers (Claude, OpenAI, Groq, OpenRouter, Gemini, custom), local LLMs (Ollama, LM Studio) or the **MCP connector** (an AI app such as Claude Code answers AION's analysis tasks). Verified live: an AI connected over MCP produced the root cause and a fix that passed all validation; a human approved and deployed it. Details: `docs/logs/2026-10-05-07-phase4-ai-connectivity.md`.

**Phase 3 — security hardening: complete.** Docker sandbox verified live (image `aion-sandbox:py310`, evaluation 4/4 with every validation step inside containers). Login + roles, service token, two-person rule, prompt redaction and the Docker sandbox are implemented and tested. Remaining: build the sandbox image and run the real-container test once Docker Desktop's disk image is moved to D: (`scripts\build-sandbox.ps1`). Details: `docs/logs/2026-10-04-06-phase3-security.md`.

## Known bugs
- None open. Four bugs found during live testing were fixed (see `docs/logs/2026-10-04-03-…`).

## Known limitations
- No SSO/MFA (local accounts); login lockout is per username and in memory.
- Validation runs on the host unless `AION_SANDBOX=docker` is set (the sandbox image must be built first).
- Python stack traces only; logs-only detection with fixed thresholds; hand-tuned correlation weights.
- Staging/production are local processes; replay covers GET/HEAD requests only.
- Single worker thread; SQLite; no schema migrations (delete `workspace/aion.db` after model changes).
- No automatic rollback.
- Prompt redaction is pattern-based (secrets, e-mails, phones, cards); names/addresses are not detected.
Full list: `docs/ROADMAP.md`.

## Important technical decisions (summary — full reasoning in `docs/DECISIONS.md`)
Modular monolith (FastAPI + SQLite/SQLAlchemy + React/Vite) · in-process single worker · structured JSON logs · regex templating + stack fingerprints · spike-vs-baseline detection · git CLI · blame-based explainable correlation · provider-neutral LLM layer, Claude by default · evidence pack instead of vector RAG · evidence IDs + grounding · deterministic fallback, clearly labelled · search/replace patches · code-enforced patch policy · worktree per attempt · local CI runner with staging replay · approval as a state-machine gate bound to a SHA · GitOps fast-forward deployment with verification · append-only audit.

## What remains
0. (Optional) Run the evaluation with Claude for a stronger-model comparison.
1. ~~Authentication and approver roles~~ ✔ Phase 3 · ~~Container sandbox~~ ✔ (needs Docker) · ~~Redaction~~ ✔
2. OIDC single sign-on + MFA for shared deployments.
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

# one-time: create your account (asks for a password)
backend\.venv\Scripts\python -m aion.cli users add <your-name> --role admin

# terminal 1
cd backend; .venv\Scripts\python -m aion          # dashboard: http://127.0.0.1:8000 - sign in

# terminal 2
backend\.venv\Scripts\python demo\run_demo.py --fresh
```
Optional AI: edit `backend\.env` (`ANTHROPIC_API_KEY=…`, or `AION_OPENAI_BASE_URL` + `AION_OPENAI_MODEL` for LM Studio/Ollama) and restart AION. Step-by-step demo script: `docs/DEMO.md`.
