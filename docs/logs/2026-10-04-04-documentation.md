# 04 — Documentation and learning system

**Date:** 2026-10-04
**Task:** Create the learning notes, decision log, interview preparation and project status.

## What changed
- `docs/DECISIONS.md` — 26 decisions in the required format (context, options, decision, reason, trade-offs, consequences, reconsideration), including what was deliberately *not* built.
- `docs/notes/README.md` — ordered learning path in 8 stages with levels, prerequisites and AION connections.
- `docs/notes/project/` — 13 notes: what AION is, architecture (data/request/AI flows, API table), lifecycle, database, log pipeline, git correlation, RCA/AI layer, patch generation, validation, approval/deployment/audit, demo walkthrough, frontend, limitations/roadmap.
- `docs/notes/concepts/` — 15 notes following the 15-point structure (AIOps, HTTP/REST, FastAPI/Pydantic, databases, concurrency, logging, dedup/detection, git, LLMs, RAG/context engineering, automated program repair, pytest, CI/CD/GitOps, HITL/state machines, React/Vite), each ending with interview questions and AION-specific answers.
- `docs/interview/README.md` — question bank (top 20 + technology, AI/RAG, workflow, curveball questions).
- `PROJECT_STATUS.md`, root `README.md`, `scripts/setup.ps1`, `docs/DEMO.md` (run/demo guide), `docs/ROADMAP.md`.
- The learning notes (`docs/notes/`) and interview preparation (`docs/interview/`) are personal study material and are kept out of git (`.gitignore`).

## Checks performed
- Every file path, function name, threshold and weight quoted in the notes was taken from the current code (e.g. weights 0.40/0.20/0.15/0.20/0.05, stable factor 0.5, window 60 s / min 5 / baseline 1800 s / ratio 3×, policy limits 5 files / 200 lines).
- Real outputs from the live runs (audit trail, validation summaries) are quoted as examples.

## Status
Documentation reflects the codebase as of this milestone.

## Next step
Post-MVP roadmap (see `docs/ROADMAP.md`), starting with authentication and sandboxed validation; and a run with a real LLM once a key or local model is configured.
