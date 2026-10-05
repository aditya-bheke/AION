# Running and Demonstrating AION


## One-time setup (Windows, PowerShell, from the repository root)

```powershell
# 1. Backend: virtual environment + dependencies
python -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt

# 2. Dashboard: install + production build (served by the backend)
cd frontend; npm install; npm run build; cd ..

# 3. (Optional) enable an LLM - see "Choosing the AI mode" below
copy backend\.env.example backend\.env
```
Or simply run `scripts\setup.ps1`, which does steps 1–2.

Requirements: Python 3.10+, Node 18+, Git.

## Accounts (one time)

AION requires sign-in. Create your first account (you are asked for a password, min 10 characters):
```powershell
backend\.venv\Scripts\python -m aion.cli users add aditya --role admin --name "Aditya"
backend\.venv\Scripts\python -m aion.cli users add riya --role approver      # optional, e.g. for the two-person rule
backend\.venv\Scripts\python -m aion.cli users list
```
Roles: **viewer** (read) · **engineer** (+ re-run investigations) · **approver** (+ approve / reject / deploy) · **admin** (everything).
The demo and log shippers authenticate with the **service token** in `backend\.env` (`AION_SERVICE_TOKEN`), created by `scripts\setup.ps1` or `python -m aion.cli service-token --write`.

## Run the demo (two terminals)

**Terminal 1 — AION:**
```powershell
cd backend
.venv\Scripts\python -m aion
```
Open **http://127.0.0.1:8000** and sign in. (Interactive API docs: http://127.0.0.1:8000/docs.)

**Terminal 2 — the monitored service + traffic:**
```powershell
backend\.venv\Scripts\python demo\run_demo.py --fresh
```
This builds `workspace/orders-service` (a real git repo, 7 commits), registers it with AION, records deployments v1.3.0 and v1.4.0, starts the service on port 8101 under a small GitOps controller, and sends ~4 requests/second. After **45 seconds** customers start using the expired coupon `SUMMER23`. Options: `--incident-after 20`, `--rate 6`, `--duration 300`. `--fresh` rebuilds the repo; omit it to keep the current state.

To reset everything: stop both terminals and delete the `workspace/` folder.

### Other bug scenarios

```powershell
backend\.venv\Scripts\python demo\run_demo.py --list                              # describe all scenarios
backend\.venv\Scripts\python demo\run_demo.py --fresh --scenario supplier-feed    # pick one
```

| Scenario | Bug | What it shows |
|---|---|---|
| `expired-coupon` (default) | `TypeError` — expired coupon → `None` | culprit commit changed the crashing line; blame finds it directly |
| `supplier-feed` | `KeyError: 'price'` — new product uses `unit_price` | culprit changed only *data*; blame points at innocent old code — needs the LLM to read the diffs |
| `empty-cart-average` | `ZeroDivisionError` on an empty draft cart | a condition that was harmless for a day becomes fatal after a new feature |
| `healthy-release` | none | a harmless release with background noise: AION must stay silent |

## Evaluating AION on all scenarios

```powershell
backend\.venv\Scripts\python evaluation\run_eval.py                 # deterministic mode (no LLM)
backend\.venv\Scripts\python evaluation\run_eval.py --mode llm      # the model configured in backend\.env
```
Each scenario runs in an isolated temporary workspace through the real pipeline; results (table + details) are written to `evaluation/results/`. Method and latest results: [EVALUATION.md](EVALUATION.md).

## What to show, step by step (≈ 8 minutes)

1. **Before the incident** — *Incidents* is empty. *System* shows the AI mode, detection parameters and the deployment history (v1.3.0 two days ago, v1.4.0 three hours ago). Point out the terminal: requests are succeeding; some payment calls return 503 (a known flaky gateway) — that's background noise.
2. **Detection** — ~5 seconds after `SUMMER23` traffic starts, incident #1 appears: `TypeError: 'NoneType' object is not subscriptable`. Open it. The stepper is animating through *Root cause → Patch → Validation*; the banner says **"AI pipeline running — production is locked"**.
3. **Logs tab** — "N raw log lines … collapsed into M templates". The incident template is highlighted; the payment timeouts and cache-miss warnings are shown separately. Show the stack trace.
4. **Git correlation tab** — the campaign commit at 1.00 with reasons (*last modified the failing line `app/pricing.py:17` [git blame]*, *shipped in v1.4.0*…); the unrelated logging commit from the same deployment ranks lower; an old coupon commit is damped because it ran fine for days.
5. **Root cause tab** — the probable root cause, confidence bar, suspected commit, **observed evidence** (each with an ID like `TRACE-1`) vs **inferences** (with "based on" IDs). If an LLM is configured, its analyzer name appears here; otherwise "heuristic (no LLM)".
6. **What the AI saw tab** — the exact evidence pack. Emphasise: *bounded, curated, cited; not raw logs.*
7. **Patch tab** — the branch `aion/incident-1-a1`, the commit, rationale and coloured diff.
8. **Validation tab** — five steps with timings; expand outputs; the replay table shows each failing production request now returning non-5xx and baseline requests unchanged.
9. **Approval gate** — the yellow banner **"Human approval required"**. Show that deploying is impossible: in a terminal,
   `curl -X POST http://127.0.0.1:8000/api/incidents/1/deploy -H "Content-Type: application/json" -d "{\"actor\":\"x\"}"` → **409**.
   Then add a comment and click **Approve patch** — the approval is recorded under your signed-in account. (Sign in as a *viewer* to show that the buttons are not offered, and the API returns 403.)
10. **Deploy** — click **Deploy to production**. Terminal 2 prints `[controller] production branch moved … redeploying`. Within seconds the banner turns green: **"Resolved — fix deployed and verified in production"**. The traffic counter's 5xx count stops increasing.
11. **Audit trail tab** — the full story with actors: `system:detector`, `system:correlator`, `ai:…`/`system:heuristic-analyzer`, `system:validator`, `human:<you>`, `system:deployer`.
12. **Prove it in git** (optional): `git -C workspace/orders-service log --oneline -3` shows the AION fix commit on `main`.

## Choosing the AI mode

| Mode | `backend/.env` | What changes |
|---|---|---|
| No LLM (default) | nothing | Heuristic RCA; patch = `git revert` of suspect commit; labelled everywhere |
| Claude | `ANTHROPIC_API_KEY=…` (model defaults to `claude-opus-5-5`) | LLM RCA citing evidence; LLM-written fix + regression test (`regression_reproduce` step runs) |
| Local model (free) | `AION_OPENAI_BASE_URL=http://127.0.0.1:11434/v1`, `AION_OPENAI_MODEL=qwen2.5-coder:7b` | Same as Claude but via Ollama (or LM Studio / any OpenAI-compatible server). The 7B model diagnoses well but its fixes usually fail validation; AION then falls back to reverting the suspect commit (labelled, validated, still human-approved) |

Restart AION after editing `.env`. The top-right pill in the dashboard shows the active mode.

### Local model with Ollama (free, everything on D:)

```powershell
# one-time: portable Ollama in D:\Ollama + model qwen2.5-coder:7b (~4.7 GB) in D:\Ollama\models
powershell -ExecutionPolicy Bypass -File scripts\setup-ollama.ps1

# every session, in its own terminal (keep it open):
powershell -ExecutionPolicy Bypass -File scripts\start-ollama.ps1
```
`start-ollama.ps1` sets a **12,288-token context window**. This matters: AION's root-cause prompts are ~6–7k tokens and Ollama's default (4,096) would silently cut off their beginning. A 6 GB GPU holds most of the 7B model; the rest runs on the CPU, so expect roughly 1–3 minutes per incident.

## Running the tests

```powershell
cd backend
.venv\Scripts\python -m pytest -q
```
44 tests, ~55 s: unit tests for every component, three end-to-end tests that build the demo repo, generate real logs from the real service, run the full pipeline (including starting a staging server), enforce the approval gate and deploy, and checks that every evaluation scenario builds with a latent bug and a known culprit.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `AION is not reachable` from `run_demo.py` | start Terminal 1 first |
| Port 8000/8101 in use | another AION/demo still running; close it (Task Manager → python.exe) |
| Dashboard shows `{"detail":"Not Found"}` at `/` | build the frontend (`npm run build`) or use `npm run dev` on port 5173 |
| Incident stuck in `error` after restarting AION | expected: in-flight jobs are interrupted on restart; click *Re-run investigation* |
| `deploy_failed: Production did not come up on the new commit` | the demo terminal (controller) is not running |

## Security settings (Phase 3)

| Setting in `backend\.env` | Effect |
|---|---|
| `AION_REQUIRED_APPROVALS=2` | two-person rule: two different approvers before deploy |
| `AION_SANDBOX=docker` | AI-written code is validated in isolated containers (build the image first: `scripts\build-sandbox.ps1`, Docker Desktop running) |
| `AION_REDACT_PROMPTS=true` (default) | secrets and personal data masked before anything reaches an LLM — see the *What the AI saw* tab |

## Choosing the AI (Phase 4): API key, local LLM or MCP connector

As an **admin**, open **System → AI provider** in the dashboard, pick a provider and click **Save**, then **Test connection**. New incidents use it immediately (no restart). **Use .env settings** returns to `backend\.env`.

| Option | What you enter | Notes |
|---|---|---|
| Anthropic Claude | API key (model defaults to `claude-opus-5-5`) | best quality |
| OpenAI / Groq / OpenRouter / Gemini | API key + model id | via each provider's OpenAI-compatible endpoint |
| Local: Ollama / LM Studio | model id (Ollama default `qwen2.5-coder:7b`) | free; start Ollama with `scripts\start-ollama.ps1` |
| Custom endpoint | URL + model (+ key) | any OpenAI-compatible server |
| **MCP connector** | nothing | an AI app you already use (e.g. Claude Code) answers AION's tasks — see below |

API keys are **encrypted** in the database with `AION_SECRET_KEY` (created by `setup.ps1` or `python -m aion.cli secret-key --write`) and are never shown again — only their last 4 characters.

### Using the MCP connector with Claude Code

1. Make sure `backend\.env` has `AION_AGENT_TOKEN` (`python -m aion.cli agent-token --write`, then restart AION).
2. Register AION's MCP server with Claude Code (once):
   ```powershell
   claude mcp add aion -- D:\projects\AION\backend\.venv\Scripts\python.exe -m aion.mcp_server
   ```
   (Claude Desktop: add the same command under `mcpServers` in `claude_desktop_config.json`.)
3. In the dashboard choose **AI provider → MCP connector** and save.
4. When an incident appears, its page shows *"Waiting for the AI agent connected over MCP"*. In Claude Code ask: **"Check AION for pending tasks and complete them."** Claude reads the evidence (`aion_get_task`) and submits the root cause and then the fix (`aion_submit_task_result`).
5. AION validates, grounds and tests the answers as usual — then **you** approve and deploy in the dashboard. The MCP server has no approve/deploy tool.

If no agent answers within `AION_MCP_TASK_TIMEOUT` (default 900 s), AION falls back to its deterministic analyzer.

## Rolling back a fix (Phase 5)

On a **resolved** incident an approver sees **Roll back this fix**. AION reverts the fix commit on `main` (a new commit — history is kept), the demo's GitOps controller redeploys it, and AION checks that production reports the revert commit; the incident becomes **Rolled back** (the original bug is back, so new errors attach to it; you can re-run the investigation or close it). If a deployment fails its post-deploy verification, AION rolls it back automatically (`AION_AUTO_ROLLBACK=true`).
