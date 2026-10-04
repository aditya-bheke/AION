# AION — Autonomous Incident Observation & Navigation

AION is an AI-assisted production incident response and remediation platform. It takes a software incident from **detection** through **root-cause analysis** and **code-fix generation** to **validated, human-approved deployment** — in one auditable workflow.

```
Logs ─► Detection ─► Dedup ─► Git/deployment correlation ─► Root-cause analysis (evidence-cited)
     ─► Candidate patch (isolated branch) ─► Validation (tests · regression · staging · traffic replay)
     ─► 🔒 HUMAN APPROVAL ─► Production deployment ─► Verification ─► Audit trail
```

AI may investigate, analyse, propose, validate and prepare. **Only a human can approve production deployment**, and the approval is bound to the exact commit that was validated.

## Quick start (Windows / PowerShell)

Requirements: Python 3.10+, Node.js 18+, Git.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1      # venv, dependencies, dashboard build

# Terminal 1 — AION
cd backend; .venv\Scripts\python -m aion                          # http://127.0.0.1:8000  (API docs: /docs)

# Terminal 2 — demo service in "production" + realistic traffic; bug triggers after 45 s
backend\.venv\Scripts\python demo\run_demo.py --fresh
```

Watch the incident appear in the dashboard, review it, approve, deploy. Full demo script: [docs/DEMO.md](docs/DEMO.md).

**AI mode:** without configuration AION runs a clearly labelled deterministic analyzer and proposes a `git revert` of the suspect commit. To enable LLM root-cause analysis and AI-written fixes, copy `backend/.env.example` to `backend/.env` and set `ANTHROPIC_API_KEY` (Claude, default model `claude-opus-5-5`) or an OpenAI-compatible endpoint such as LM Studio / Ollama.

**Tests:** `cd backend; .venv\Scripts\python -m pytest -q` (33 tests, including full end-to-end workflow tests).

## Repository layout

```
backend/            FastAPI application (package `aion`) + tests
  aion/logs/        collection, normalisation, deduplication, detection
  aion/gitops/      git wrapper, commit/deployment correlation
  aion/ai/          LLM providers, evidence pack, RCA + grounding, patch prompts
  aion/remediation/ worktrees, patch application, patch policy
  aion/validation/  CI-style validation runner (tests, staging, replay)
  aion/deploy/      approval-checked deployment + production verification
  aion/pipeline/    background worker + orchestrator
  aion/api/         REST endpoints
frontend/           React + Vite dashboard
demo/               monitored demo service (git history overlays), repo builder, demo driver
docs/               demo guide, decisions, roadmap, development log
scripts/            setup script
workspace/          runtime data (created at run time; git-ignored)
```

## Documentation

| Start here | |
|---|---|
| [docs/DEMO.md](docs/DEMO.md) | How to run and demonstrate AION, AI modes, troubleshooting |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Every technical decision with options, reasons and trade-offs |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Known limitations and post-MVP roadmap |
| [docs/logs/](docs/logs/) | Development log |
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | Current status, limitations, roadmap |

## Project

BE Computer Engineering final-year project. Areas: AIOps, log analysis, incident detection, root-cause analysis, LLM-based analysis, automated program repair, Git/code-change analysis, automated patch validation, CI/CD, human-in-the-loop deployment.
