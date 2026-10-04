# 01 — Repository assessment, architecture and MVP scope

**Date:** 2026-10-04
**Task:** Inspect the repository, choose the architecture and define the MVP.

## What we found
- `D:\projects\AION` was **empty** (no files, not a git repository). Everything is built from scratch.
- Machine: Windows 11, Python 3.10, Node 22, Git 2.52, Docker available, RTX 3050 (6 GB VRAM).
- No LLM API keys in the environment; LM Studio installed but with no models downloaded; no Ollama.

## Decisions taken (details in DECISIONS.md)
- MVP = every workflow stage working for real, for one Python service, locally (D-01).
- Modular monolith: Python + FastAPI + SQLite/SQLAlchemy + React/Vite (D-02…D-05).
- Provider-neutral LLM layer: Claude (official SDK) by default, OpenAI-compatible adapter for local models, and an honest deterministic fallback so the workflow runs without any key (D-12, D-15).
- No vector DB: exact, structured retrieval into an evidence pack (D-13).
- Human approval as a state-machine gate bound to a commit SHA (D-21).
- A realistic demo service with real git history and a latent bug, because AION needs something real to observe (D-25).

## Files/components affected
`git init`, `backend/` skeleton with virtual environment (`backend/.venv`) and `requirements.txt`, directory layout for `frontend/`, `demo/`, `docs/`.

## Problems encountered
- No LLM available on the machine → designed the fallback analyzer and revert strategy so the MVP is demonstrable today, while the LLM path is exercised in tests via a scripted test double and works as soon as a key/local model is configured.

## Status
Architecture fixed; implementation started.

## Next step
Implement the backend core.
