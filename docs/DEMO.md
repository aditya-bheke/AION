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

## Run the demo (two terminals)

**Terminal 1 — AION:**
```powershell
cd backend
.venv\Scripts\python -m aion
```
Open **http://127.0.0.1:8000** (dashboard) and **http://127.0.0.1:8000/docs** (interactive API docs).

**Terminal 2 — the monitored service + traffic:**
```powershell
backend\.venv\Scripts\python demo\run_demo.py --fresh
```
This builds `workspace/orders-service` (a real git repo, 7 commits), registers it with AION, records deployments v1.3.0 and v1.4.0, starts the service on port 8101 under a small GitOps controller, and sends ~4 requests/second. After **45 seconds** customers start using the expired coupon `SUMMER23`. Options: `--incident-after 20`, `--rate 6`, `--duration 300`. `--fresh` rebuilds the repo; omit it to keep the current state.

To reset everything: stop both terminals and delete the `workspace/` folder.

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
   Then type your name + comment and click **Approve patch**.
10. **Deploy** — click **Deploy to production**. Terminal 2 prints `[controller] production branch moved … redeploying`. Within seconds the banner turns green: **"Resolved — fix deployed and verified in production"**. The traffic counter's 5xx count stops increasing.
11. **Audit trail tab** — the full story with actors: `system:detector`, `system:correlator`, `ai:…`/`system:heuristic-analyzer`, `system:validator`, `human:<you>`, `system:deployer`.
12. **Prove it in git** (optional): `git -C workspace/orders-service log --oneline -3` shows the AION fix commit on `main`.

## Choosing the AI mode

| Mode | `backend/.env` | What changes |
|---|---|---|
| No LLM (default) | nothing | Heuristic RCA; patch = `git revert` of suspect commit; labelled everywhere |
| Claude | `ANTHROPIC_API_KEY=…` (model defaults to `claude-opus-5-5`) | LLM RCA citing evidence; LLM-written fix + regression test (`regression_reproduce` step runs) |
| Local model (free) | `AION_OPENAI_BASE_URL=http://localhost:1234/v1`, `AION_OPENAI_MODEL=<model id>` | Same as Claude but via LM Studio/Ollama; weaker models produce weaker fixes — validation will catch broken ones |

Restart AION after editing `.env`. The top-right pill in the dashboard shows the active mode.

For LM Studio: download a coder model that fits your GPU (e.g. *Qwen2.5-Coder-7B-Instruct*, Q4_K_M ≈ 4.7 GB for a 6 GB GPU), load it, start the local server (Developer tab → Start Server, port 1234), and use the model identifier shown there.

## Running the tests

```powershell
cd backend
.venv\Scripts\python -m pytest -q
```
33 tests, ~30 s: unit tests for every component plus three end-to-end tests that build the demo repo, generate real logs from the real service, run the full pipeline (including starting a staging server), enforce the approval gate and deploy.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `AION is not reachable` from `run_demo.py` | start Terminal 1 first |
| Port 8000/8101 in use | another AION/demo still running; close it (Task Manager → python.exe) |
| Dashboard shows `{"detail":"Not Found"}` at `/` | build the frontend (`npm run build`) or use `npm run dev` on port 5173 |
| Incident stuck in `error` after restarting AION | expected: in-flight jobs are interrupted on restart; click *Re-run investigation* |
| `deploy_failed: Production did not come up on the new commit` | the demo terminal (controller) is not running |
