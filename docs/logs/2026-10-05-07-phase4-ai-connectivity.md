# 07 — Phase 4: AI connectivity (API keys, local LLM, MCP connector)

**Date:** 2026-10-05
**Task:** Let users choose how AION gets its AI — an API key for a hosted model, a local LLM, or an MCP connector — from the dashboard.

## What changed
| Area | Files | Summary |
|---|---|---|
| Provider choice | `ai/providers/factory.py`, `api/ai_config.py`, `models.py` (AIProviderConfig), `secrets_store.py` | presets (Claude, OpenAI, Groq, OpenRouter, Gemini, Ollama, LM Studio, custom, MCP, none); dashboard config overrides `.env`; API keys Fernet-encrypted with `AION_SECRET_KEY`, shown only as `…abcd`; test-connection endpoint; admin-only changes; audited |
| MCP connector | `ai/providers/mcp_bridge.py`, `api/agent.py`, `mcp_server.py`, `models.py` (AITask), `security.py` (agent token) | pipeline model calls become tasks; agents list/read/answer them through 5 MCP tools; answers validated on submission; agent token cannot approve/deploy/ingest |
| CLI / setup | `cli.py` (`agent-token`, `secret-key`), `scripts/setup.ps1`, `backend/pyproject.toml` | tokens/keys generated into `.env`; `aion` installed editable so `python -m aion...` works from any folder |
| Dashboard | `AiProviderCard.jsx`, `SystemPage.jsx`, `ApprovalPanel.jsx`, `api.js` | provider form (preset, model, URL, key, effort), save/test/reset, MCP instructions + agent status; incident shows "waiting for the MCP agent" |

## Tests
77 passing, 1 skipped: `test_ai_config.py` (key encrypted at rest and never returned or audited, keys not reused across providers, admin-only, missing master key → 409, reset to .env), `test_mcp_connector.py` (full pipeline answered by an agent through the agent API → awaiting approval; agent token rejected by approve/deploy/ingest; invalid answers rejected with the task kept open; timeout → deterministic fallback; MCP tool functions; **real stdio MCP handshake** listing exactly 5 tools, none approve/deploy).

**Live MCP run** (scratch database, AION in MCP mode, demo traffic): a real MCP client connected to `python -m aion.mcp_server`; the analyst (Claude, acting as the connected agent) read task #1 and submitted an evidence-cited RCA (confidence 0.93), then task #2 — a fix raising `InvalidCoupon` → HTTP 400 plus a regression test. Validation: syntax ✓, regression test fails on old code ✓, 12 tests ✓, staging ✓, 14 incident requests fixed / 10 baseline unchanged ✓. A signed-in approver approved and deployed; production returns `400 Coupon SUMMER23 is invalid or expired`, valid coupons still 200. First AI-written (not revert) fix deployed in the project.

## Problems encountered
1. **The pipeline called the model inside an open SQLite write transaction.** The MCP bridge (which writes a task row) deadlocked ("database is locked"); with any slow model the same lock would have blocked the log collector for the whole call. Found by the MCP end-to-end test. → commit before every model call (RCA stage and patch creation).
2. Running `python -m aion.cli` from the repo root failed (`No module named 'aion'`) — the package was only importable from `backend/`. → `backend/pyproject.toml` + editable install (`pip install -e backend`, now in `setup.ps1`).
3. `mcp` 2.x renamed `FastMCP` to `MCPServer`; checked the installed SDK's API before writing the server.
4. A background demo started from the wrong directory during the live test (relative path) → re-run with absolute paths.

## Status
Phase 4 complete. Docker sandbox live check still waits for the Docker disk move (Phase 3).
