# AION — Technical Decision Log

Every meaningful technical decision in AION is recorded here with its context, the options considered, and the trade-offs. When a decision changes, **do not delete the old entry**: mark it `Superseded by D-xx` and add a new one. In a viva, this file is your answer to "why did you do it this way?".

Format of each entry: Context → Options → Decision → Reason → Trade-offs → Consequences → Future reconsideration.

| # | Decision | Area | Status |
|---|----------|------|--------|
| [D-01](#d-01-mvp-scope-one-complete-workflow-for-one-language) | MVP scope: one complete workflow, one language | Scope | Accepted |
| [D-02](#d-02-modular-monolith-instead-of-microservices) | Modular monolith instead of microservices | Architecture | Accepted |
| [D-03](#d-03-python--fastapi-for-the-backend) | Python + FastAPI backend | Backend | Accepted |
| [D-04](#d-04-sqlite--sqlalchemy-20-orm) | SQLite + SQLAlchemy 2.0 | Database | Accepted |
| [D-05](#d-05-react--vite-dashboard-with-polling) | React + Vite dashboard with polling | Frontend | Accepted |
| [D-06](#d-06-in-process-single-worker-thread-for-background-jobs) | In-process single worker thread | Concurrency | Accepted |
| [D-07](#d-07-structured-json-logs-file-tail-collector--http-ingest-api) | Structured JSON logs; file-tail collector + HTTP ingest | Log processing | Accepted |
| [D-08](#d-08-deduplication-by-template-masking--stack-fingerprint) | Dedup by template masking + stack fingerprint | Log processing | Accepted |
| [D-09](#d-09-per-signature-spike-detection-with-a-baseline) | Per-signature spike detection with a baseline | Detection | Accepted |
| [D-10](#d-10-call-the-git-cli-through-subprocess) | Call the git CLI through subprocess | Git | Accepted |
| [D-11](#d-11-explainable-weighted-correlation-with-git-blame) | Explainable weighted correlation with `git blame` | Git / RCA | Accepted |
| [D-12](#d-12-provider-neutral-llm-layer-claude-by-default) | Provider-neutral LLM layer, Claude by default | AI | Accepted |
| [D-13](#d-13-no-vector-database-curated-evidence-pack-instead-of-classic-rag) | No vector DB: curated evidence pack instead of classic RAG | AI | Accepted |
| [D-14](#d-14-evidence-ids-structured-output-and-grounding-checks) | Evidence IDs, structured output and grounding checks | AI safety | Accepted |
| [D-15](#d-15-deterministic-fallback-when-no-llm-is-configured) | Deterministic fallback when no LLM is configured | AI | Accepted |
| [D-16](#d-16-patches-as-searchreplace-edits) | Patches as search/replace edits | Program repair | Accepted |
| [D-17](#d-17-patch-policy-enforced-in-code) | Patch policy enforced in code | Safety | Accepted |
| [D-18](#d-18-one-git-worktree-and-branch-per-patch-attempt) | One git worktree + branch per patch attempt | Validation | Accepted |
| [D-19](#d-19-local-ci-runner-with-staging-replay) | Local CI runner with staging replay | Validation / CI | Accepted |
| [D-20](#d-20-bounded-generate-validate-repair-loop) | Bounded generate-validate-repair loop | Program repair | Accepted |
| [D-21](#d-21-human-approval-as-a-state-machine-gate-bound-to-a-commit-sha) | Human approval as a state-machine gate bound to a commit SHA | Safety | Accepted |
| [D-22](#d-22-gitops-style-deployment-with-post-deploy-verification) | GitOps-style deployment + post-deploy verification | Deployment | Accepted |
| [D-23](#d-23-no-authentication-in-the-mvp) | No authentication in the MVP | Security | Accepted (known risk) |
| [D-24](#d-24-append-only-audit-table) | Append-only audit table | Audit | Accepted |
| [D-25](#d-25-a-real-demo-service-with-synthetic-git-history) | Real demo service with synthetic git history | Demo | Accepted |
| [D-26](#d-26-intentionally-not-in-the-mvp) | Intentionally NOT in the MVP | Scope | Accepted |

---

# Decision: D-01 MVP scope: one complete workflow for one language

Date: 2026-10-04
Status: Accepted
Area: Scope

## Context
AION's vision spans log collection, detection, RCA, Git correlation, patch generation, CI/CD validation, approval and deployment. Building all of these at production depth is impossible for a first version, and building them shallowly (UI screens with mock data) would demonstrate nothing.

## Options Considered
- A. Build many features broadly (multi-language, Kubernetes, real CI, vector DB…) with shallow depth.
- B. Build only the AI part (log → LLM → explanation).
- C. Build **every stage of the workflow end-to-end, really working**, for **one realistic service in one language (Python)**, with local stand-ins for heavy infrastructure (staging = local process, CI = local runner, deploy = git fast-forward + auto-reload).

## Decision
Option C.

## Reason
The central value proposition of AION is the *connection* between stages (detection → RCA → fix → validation → approval → deploy). Only C demonstrates that. Each local stand-in sits behind a clear interface (`ValidationRunner`, `deploy()`, `LLMProvider`), so it can be replaced by the real thing later without touching the rest.

## Trade-offs
+ Fully demonstrable on one laptop, no cloud accounts.
+ Every stage is real code operating on a real git repo, real processes and real HTTP traffic.
− Only Python stack traces are parsed; only one service at a time is realistic.
− "Staging" and "production" are local processes, not separate machines.

## Consequences
The demo service (`demo/`) is a first-class part of the project. Integration tests run the whole workflow against it.

## Future Reconsideration
After the MVP: add Java/Node stack-trace parsers, a real CI provider (GitHub Actions), container-based staging.

---

# Decision: D-02 Modular monolith instead of microservices

Date: 2026-10-04
Status: Accepted
Area: Architecture

## Context
AION has many logical components (collector, detector, correlator, AI, validator, deployer, API, dashboard).

## Options Considered
- A. Microservices (one deployable per component, message broker between them).
- B. A single backend process organised into packages with clear boundaries (modular monolith).

## Decision
B. One FastAPI process; packages `logs/`, `gitops/`, `ai/`, `remediation/`, `validation/`, `deploy/`, `pipeline/`, `api/`.

## Reason
Microservices solve organisational scaling (many teams) and independent scaling of hot paths; AION has neither problem yet. A monolith is simpler to run, debug, test and explain. Boundaries are kept clean (e.g. the AI layer only sees an `LLMProvider` protocol), so components can be extracted later.

## Trade-offs
+ One command to start; one place to debug; transactions across components are trivial.
− Components cannot be scaled independently; a crash in one could affect the process (mitigated: background jobs catch all exceptions).

## Consequences
Communication between components is plain function calls + the database.

## Future Reconsideration
If log ingestion volume grows by orders of magnitude, extract the collector/ingest path into its own service behind a queue (Kafka/Redis Streams).

---

# Decision: D-03 Python + FastAPI for the backend

Date: 2026-10-04
Status: Accepted
Area: Backend

## Context
We need an HTTP API, background processing, subprocess management (git, pytest, uvicorn), and LLM SDKs.

## Options Considered
- A. Python + FastAPI
- B. Python + Flask
- C. Node.js + Express
- D. Java + Spring Boot

## Decision
A.

## Reason
Python has the best ecosystem for this domain (official Anthropic SDK, `ast` module for analysing Python source, pytest). FastAPI gives request validation through Pydantic models, automatic OpenAPI docs at `/docs`, and type hints that make the code self-documenting. The team already knows basic Python.

## Trade-offs
+ Validation and docs for free; very little boilerplate.
− Python is slower than Java/Go — irrelevant here: AION's time is spent waiting on git, tests and LLM calls, not CPU.
− FastAPI's async model must be understood (we use plain `def` endpoints, which FastAPI runs in a thread pool, because our work is blocking I/O).

## Consequences
All backend code is Python 3.10+. Request bodies are Pydantic models in `aion/schemas.py`.

## Future Reconsideration
Not expected to change.

---

# Decision: D-04 SQLite + SQLAlchemy 2.0 ORM

Date: 2026-10-04
Status: Accepted
Area: Database

## Context
AION stores services, log events, signatures, incidents, suspects, RCA reports, patches, validation runs, approvals, deployments and audit events — relational data with foreign keys.

## Options Considered
- A. SQLite via SQLAlchemy ORM
- B. PostgreSQL via SQLAlchemy ORM
- C. MongoDB (document store)
- D. Elasticsearch for logs + SQL for the rest

## Decision
A, with WAL journal mode.

## Reason
SQLite needs no server: the database is a single file (`workspace/aion.db`), ideal for a locally demonstrated project. SQLAlchemy abstracts the dialect, so switching to PostgreSQL is a connection-string change (`AION_DATABASE_URL`). The data is clearly relational (an approval belongs to a patch which belongs to an incident), which suits SQL better than a document store.

## Trade-offs
+ Zero setup; easy to inspect with any SQLite browser; trivial to reset (delete the file).
− Single writer at a time. With WAL mode readers (dashboard) are not blocked by the writer (pipeline), which is enough for one AION instance.
− Not suited to storing billions of log lines (we store only what the demo needs).
− No migrations tool yet (tables are created with `create_all`); schema changes during development mean deleting the DB.

## Consequences
JSON columns hold semi-structured data (stack frames, evidence pack, validation steps).

## Future Reconsideration
Move to PostgreSQL + Alembic migrations when running multiple AION workers or keeping long history; move raw logs to a log store (Loki/Elasticsearch/ClickHouse) at real volume.

---

# Decision: D-05 React + Vite dashboard with polling

Date: 2026-10-04
Status: Accepted
Area: Frontend

## Context
The dashboard must show the complete workflow live, including a very visible human-approval gate.

## Options Considered
- A. Server-rendered HTML templates (Jinja2) from FastAPI.
- B. React single-page app built with Vite.
- C. React + Next.js.
- Live updates: WebSockets vs Server-Sent Events vs polling.

## Decision
B, written in plain JavaScript (JSX), no router or state library, polling every 2.5–5 s.

## Reason
The incident page is a rich, live-updating view (stepper, tabs, diff viewer, approval form) — a component model is the right tool. Vite gives a fast dev server and a static production build that FastAPI serves itself, so the demo still runs as one process. Polling was chosen over WebSockets because state changes at most every few seconds and polling keeps the backend stateless; the cost (a few small GET requests) is negligible.

## Trade-offs
+ Industry-standard skills; simple deployment (static files).
− Polling has up to ~3 s latency and repeated requests.
− No TypeScript: fewer compile-time checks, but less to learn for the team.

## Consequences
Routing uses the URL hash (`#/incidents/3`), so the static file server needs no special SPA fallback.

## Future Reconsideration
Switch to Server-Sent Events if many users watch the dashboard simultaneously; add TypeScript once the UI grows.

---

# Decision: D-06 In-process single worker thread for background jobs

Date: 2026-10-04
Status: Accepted
Area: Concurrency

## Context
The pipeline (correlation, LLM calls, test runs, staging) takes seconds to minutes and must not block HTTP requests.

## Options Considered
- A. Celery or RQ with Redis as broker.
- B. FastAPI `BackgroundTasks`.
- C. A `ThreadPoolExecutor(max_workers=1)` owned by the app, plus a daemon thread for the log collector.

## Decision
C (`aion/pipeline/worker.py`).

## Reason
No extra infrastructure. A single worker serialises jobs, which avoids two jobs racing on the same git repository or SQLite writer lock. Jobs are de-duplicated by key (`incident-3`), so double-clicking "re-run" cannot start two pipelines. Every job persists its progress in the DB, so a restart loses only the in-memory job; on startup interrupted incidents are moved to `error`/`deploy_failed` with a clear message (`main._recover_interrupted_jobs`).

## Trade-offs
+ Simple, explainable, no Redis.
− Jobs are lost if the process crashes (but their state is visible and re-runnable).
− One job at a time: a second incident waits for the first.

## Future Reconsideration
Celery/RQ + Redis (or a DB-backed job table) when handling many services concurrently or running multiple AION instances.

---

# Decision: D-07 Structured JSON logs; file-tail collector + HTTP ingest API

Date: 2026-10-04
Status: Accepted
Area: Log processing

## Context
AION must receive application logs.

## Options Considered
- A. Parse free-text logs with regexes.
- B. Require structured (JSON-lines) logs.
- C. Integrate with an existing stack (ELK, Loki, Datadog) as the source.
- Transport: push (HTTP API) vs pull (tail a file).

## Decision
B, with both transports: `POST /api/ingest/{service}` (push) and a built-in file-tail collector (pull, like Filebeat/Promtail) that the demo uses.

## Reason
Structured logs are modern best practice; they give reliable fields (level, request, exception, stack trace) without fragile regexes. The collector stores its byte offset in the DB, reads only complete lines, and handles truncation/rotation. The HTTP endpoint allows any other producer.

## Trade-offs
− Services must log JSON (the demo includes a 30-line `JsonFormatter` showing how). Plain-text lines are still accepted as INFO messages.

## Future Reconsideration
Add an adapter for Loki/Elasticsearch queries so AION can investigate existing log stores instead of storing logs itself.

---

# Decision: D-08 Deduplication by template masking + stack fingerprint

Date: 2026-10-04
Status: Accepted
Area: Log processing

## Context
Thousands of lines differ only in variable values ("order 1042", "3.2ms"). The AI and the humans need the distinct *kinds* of events, with counts.

## Options Considered
- A. Exact string matching (useless: every line differs).
- B. Regex masking of variable tokens (numbers, UUIDs, IPs, hex, URLs, timestamps) → template; signature = hash(level, logger, template, exception type, innermost 3 application frames as file:function).
- C. The Drain online log-parsing algorithm (fixed-depth parse tree).
- D. Embedding-based clustering.

## Decision
B (`aion/logs/normalize.py`).

## Reason
Deterministic, fast, easy to test and to explain; good enough for structured logs where the variable parts are mostly values. Line numbers are deliberately excluded from the fingerprint so unrelated edits above the failing line don't split one error into two signatures. Library frames are excluded so framework upgrades don't either.

## Trade-offs
− Variable words (e.g. user names) are not masked, which could split a template; Drain handles that better.

## Future Reconsideration
Adopt Drain (e.g. the `drain3` library) when ingesting heterogeneous free-text logs.

---

# Decision: D-09 Per-signature spike detection with a baseline

Date: 2026-10-04
Status: Accepted
Area: Detection

## Context
Decide when a stream of errors becomes an *incident*.

## Options Considered
- A. Any ERROR line opens an incident (far too noisy).
- B. A fixed threshold per window.
- C. Threshold + spike ratio against the signature's own recent baseline.
- D. Statistical/ML anomaly detection (EWMA, Isolation Forest, LSTM).

## Decision
C (`aion/logs/detector.py`): open an incident when, in the last `window` seconds, a signature has `≥ min_count` errors **and** `≥ spike_ratio × baseline average`. Event time (log timestamps) is used, not wall-clock time. Events older than the closure of the previous incident with the same signature are not counted (added after live testing: late-arriving lines from before a fix re-opened a resolved incident); a recurrence after closure opens a new regression incident.

## Reason
A new error (baseline 0) fires quickly; a chronic low-rate error (our demo's flaky payment gateway) does not fire just because it keeps happening. The rule is explainable in one sentence, and the reason string is stored on the incident. Further events of an open incident's signature attach to it (incident-level dedup).

## Trade-offs
− Fixed parameters need tuning per service; no seasonality model; no metric-based detection (latency, CPU).

## Future Reconsideration
EWMA/z-score per signature, and metrics (Prometheus) as a second detection source.

---

# Decision: D-10 Call the git CLI through subprocess

Date: 2026-10-04
Status: Accepted
Area: Git

## Options Considered
- A. GitPython / pygit2 libraries.
- B. The `git` command-line tool via `subprocess` (argument lists, no shell).

## Decision
B (`aion/gitops/repo.py`).

## Reason
The commands (`blame --porcelain`, `show -U0`, `worktree add`, `revert --no-commit`, `merge --ff-only`) are exactly what an engineer would type, so behaviour is transparent and debuggable by copy-pasting. No native dependency. All output is parsed from stable machine formats (`--porcelain`, custom `--format`).

## Trade-offs
− Process start-up cost per command (milliseconds; irrelevant at our scale).

---

# Decision: D-11 Explainable weighted correlation with git blame

Date: 2026-10-04
Status: Accepted
Area: Git / RCA

## Context
"Which change caused this?" — the most valuable question during an incident.

## Options Considered
- A. Ask the LLM to guess from the list of recent commits.
- B. Only "the last deployment did it".
- C. A deterministic, explainable score combining several signals, then let the LLM reason over the top candidates and their diffs.
- D. The SZZ algorithm from research (find bug-introducing commits from fix commits) — needs fix history we don't have yet.

## Decision
C (`aion/gitops/correlation.py`). Signals and weights: blame of the exact failing line (0.40), blame of lines in the enclosing function found with Python's `ast` (0.20), file overlap with the stack trace (0.15), shipped in the last deployment before the incident (0.20), commit-message keyword overlap (0.05). Blame runs **at the revision that was deployed** when errors began. Each signal counts **once** per commit (its strongest instance), and a commit already in production before the suspect deployment, while the error did not occur, is multiplied by 0.5. (Both rules were added after live testing showed an older commit tying the culprit at 1.0 because blame signals were summed across stack frames.)

## Reason
Blame on the exact failing line is the strongest available evidence, and it is objective. Every point of score carries a human-readable reason shown in the dashboard. The LLM then confirms or disputes the ranking by reading the diff — two independent methods.

## Trade-offs
− Weights are hand-chosen, not learned. A bug can be caused by a change *elsewhere* (e.g. a config or a caller), which blame on the trace won't find; deployment timing partially covers that.

## Future Reconsideration
Learn weights from resolved incidents; add SZZ once AION's own fix history exists.

---

# Decision: D-12 Provider-neutral LLM layer, Claude by default

Date: 2026-10-04
Status: Accepted
Area: AI

## Context
The requirements ask for a modular AI layer where the model can be changed later.

## Options Considered
- A. Call one vendor SDK directly throughout the code.
- B. A large framework (LangChain/LlamaIndex).
- C. A tiny `LLMProvider` protocol (`complete_json(system, user, schema)`) with adapters, and a shared `generate_structured()` that validates output with Pydantic.

## Decision
C (`aion/ai/providers/`). Adapters: `AnthropicProvider` (official `anthropic` SDK; default model `claude-opus-5-5`, adaptive thinking, structured JSON-schema output, server-side refusal fallback enabled) and `OpenAICompatProvider` (any `/v1/chat/completions` server: LM Studio, Ollama, OpenAI, Groq…). Selected by environment variables.

## Reason
Business logic (RCA, patching) depends only on the protocol, so swapping models is configuration. A framework would hide exactly the parts we must be able to explain in a viva (prompt, schema, validation) behind abstractions.

## Trade-offs
− We write ~150 lines of adapter code ourselves.
− Different models differ in quality; a local 7B model will produce weaker RCA and patches than Claude — validation catches bad patches, but cannot make a weak model strong.

## Future Reconsideration
Add Bedrock/Vertex/Azure adapters if a deployment environment requires them.

---

# Decision: D-13 No vector database: curated evidence pack instead of classic RAG

Date: 2026-10-04
Status: Accepted
Area: AI

## Context
The requirements suggest RAG "only where it genuinely improves retrieval".

## Options Considered
- A. Embed all logs/code/commits into a vector DB (Chroma/FAISS) and retrieve top-k chunks by similarity.
- B. Send everything (all logs, whole repo) to the LLM.
- C. **Deterministic, structured retrieval**: the stack trace tells us exactly which files/functions matter; `git blame` and the deployment window tell us exactly which commits matter; dedup tells us which log clusters exist. Assemble these into an "evidence pack" with IDs. For past incidents use exact-signature match + token-overlap (Jaccard) similarity.

## Decision
C (`aion/ai/context.py`).

## Reason
For this problem the relevant context is *precisely addressable*: a traceback names `app/pricing.py:17 in apply_discount`. Semantic similarity search would be a fuzzier way to find something we can find exactly. B is wasteful and harmful: thousands of duplicate lines dilute the model's attention and cost tokens. It is still retrieval-augmented generation in the general sense — the retrieval is just exact rather than vector-based. Past-incident retrieval is lexical because the history is small and highly structured.

## Trade-offs
− When the stack trace doesn't point to the cause (e.g. a config change), exact retrieval misses context that semantic search over docs/runbooks might find.

## Future Reconsideration
Add a vector index for **runbooks/documentation and large incident history**, where queries are natural language and exact keys don't exist.

---

# Decision: D-14 Evidence IDs, structured output and grounding checks

Date: 2026-10-04
Status: Accepted
Area: AI safety

## Context
LLMs can hallucinate files, commits or log lines. The requirements ask to distinguish observed evidence from inferred conclusions.

## Decision
1. Every evidence item has an ID (`LOG-2`, `TRACE-1`, `COMMIT-69cfda3`, `CODE-1`, `DEPLOY-1`, `INC-4`).
2. The model must return JSON matching a schema (`RCAOutput`) with **separate** `observed_evidence` (each citing one ID) and `inferences` (each listing supporting IDs), plus calibrated `confidence`.
3. `ground()` (in `aion/ai/rca.py`) then checks the answer against reality: unknown evidence IDs are removed, files not present in the repo are removed, a suspected commit must be one of the candidates (short SHAs are expanded), and confidence is capped (0.6, or 0.3 if nothing verifiable remains). Every correction is shown as a warning in the dashboard.
4. Invalid JSON gets exactly one "repair" retry with the validation error; after that the call fails loudly.

## Reason
Hallucination is reduced by constraining *inputs* (curated evidence), constraining *outputs* (schema + citations) and *verifying* outputs (grounding). None of the three alone is sufficient.

## Trade-offs
− Grounding checks existence, not truth: a model can cite a real ID and still misread it. That is why the patch is validated by tests and the human reviews.

---

# Decision: D-15 Deterministic fallback when no LLM is configured

Date: 2026-10-04
Status: Accepted
Area: AI

## Context
The team may not have an API key during development or a demo, and an LLM API can be down.

## Decision
If no provider is configured (or the LLM call fails), the **heuristic analyzer** builds the RCA from the correlation results, and the patch strategy becomes **`git revert` of the suspected commit**. Both are labelled explicitly ("heuristic (no LLM)", "deterministic git revert (no LLM)") in the DB, UI and audit trail.

## Reason
Keeps the whole workflow functional and honest: no fake "AI" text is ever produced. Reverting the offending change is also what real on-call engineers often do first.

## Trade-offs
− A revert removes the feature that commit added; the rationale says so. A revert can conflict with later commits, in which case validation fails and a human must step in.

---

# Decision: D-16 Patches as search/replace edits

Date: 2026-10-04
Status: Accepted
Area: Program repair

## Options Considered
- A. Ask the model for a unified diff.
- B. Ask for the complete new file content.
- C. Ask for search/replace blocks: exact snippet of current code + replacement.

## Decision
C (`aion/ai/patcher.py`, `aion/remediation/apply.py`), plus optional *new* regression-test files.

## Reason
Models frequently produce malformed diff hunk headers (A), and rewriting whole files (B) risks silently changing unrelated code. With C, application is deterministic: the snippet must occur exactly once, all edits apply or none do, CRLF/LF differences are handled. The real unified diff is then produced by git from the resulting commit.

---

# Decision: D-17 Patch policy enforced in code

Date: 2026-10-04
Status: Accepted
Area: Safety

## Decision
`aion/remediation/policy.py` rejects: absolute paths, `..`, editing existing tests, CI config, dependency files or `.git`; creating any new file except `tests/test_aion_*.py`; more than 5 files or 200 changed lines.

## Reason
Prompts are requests, not guarantees. A model must not be able to "fix" a failing build by deleting a test or loosening a dependency. Enforcement in code works even if the model ignores its instructions or is manipulated by malicious content in logs (prompt injection).

---

# Decision: D-18 One git worktree and branch per patch attempt

Date: 2026-10-04
Status: Accepted
Area: Validation

## Decision
Each attempt gets `workspace/worktrees/<service>/incident-<id>-a<n>` on branch `aion/incident-<id>-a<n>`, created from the production branch head. The patch is a real commit on that branch.

## Reason
`git worktree` gives a second checkout of the same repository without copying history: production's checkout is never touched while validating. A commit gives a content hash (SHA) that later binds the human approval to exactly what was tested.

---

# Decision: D-19 Local CI runner with staging replay

Date: 2026-10-04
Status: Accepted
Area: Validation / CI

## Context
The requirements call for automated validation and CI/staging.

## Decision
`aion/validation/runner.py` runs a pipeline modelled on CI: (1) syntax check of changed files, (2) *fail-to-pass* check — new regression tests must fail on the unpatched code (advisory), (3) the service's full test suite, (4) "staging deploy": start the patched service from the worktree on a free port and wait for `/health`, (5) **replay** the GET requests that failed in production (expect no 5xx) and a sample of previously successful requests (expect the same status). Commands come from the service registration, never from the AI, and run without a shell. Only idempotent (GET/HEAD) requests are replayed.

## Reason
Unit tests alone passed *before* the bug too — that is why it reached production. Replaying real failing traffic against a running staging instance tests the actual symptom; replaying good traffic catches regressions.

## Trade-offs
− AI-generated code is executed on the host (in a separate process, with timeouts) — acceptable on a dev machine, **not** acceptable in production. See D-26.
− Staging uses the same machine and in-memory data, so environment-specific bugs are out of reach.

## Future Reconsideration
Run steps in a Docker container with no network; delegate to GitHub Actions/GitLab CI through a `CIRunner` interface; deploy staging to a real environment.

---

# Decision: D-20 Bounded generate-validate-repair loop

Date: 2026-10-04
Status: Accepted
Area: Program repair

## Decision
In LLM mode, if a patch fails to apply or fails validation, the failure output (test failures, staging logs) is fed back to the model for a second attempt. Maximum attempts: `AION_MAX_PATCH_ATTEMPTS` (default 2). Then the incident goes to `validation_failed` for a human.

## Reason
Feedback-driven repair measurably improves automated program repair, but unbounded loops waste money and time and can "overfit" to tests.

---

# Decision: D-21 Human approval as a state-machine gate bound to a commit SHA

Date: 2026-10-04
Status: Accepted
Area: Safety / human-in-the-loop

## Decision
Incident status is an explicit finite-state machine (`aion/lifecycle.py`). The **only** edge into `deploying` is from `approved`; the only way into `approved` is the human approval endpoint, which also requires a validated patch and records `Approval(approver, comment, commit_sha)`. The deployer re-checks, in code, that an approval exists for exactly the commit being deployed and that its validation passed. Approval and deployment are two separate human actions. A unit test asserts that no other state can reach `deploying`.

## Reason
"The AI cannot deploy" must be a structural property, not a convention: the automated pipeline (`orchestrator.run_pipeline`) has no code path that reaches deployment, and the state machine rejects illegal transitions even if someone adds one by mistake.

## Trade-offs
− Approver identity is a typed name (see D-23).

---

# Decision: D-22 GitOps-style deployment with post-deploy verification

Date: 2026-10-04
Status: Accepted
Area: Deployment

## Decision
Deploying = `git merge --ff-only <fix-branch>` on the production branch's checkout (only if the checkout is clean and the production branch has not moved since validation). A controller restarts the production runtime when the branch moves (demo: `ProductionRuntime` in `demo/run_demo.py`; originally `uvicorn --reload`, replaced because it did not reload after the merge on Windows and orphaned a worker process — AION's verification caught the stale deployment). AION then waits until `/health` reports the new commit and replays the incident's failing requests against production → `resolved`, or `deploy_failed` with details.

## Reason
In GitOps, the production branch *is* the desired state and a controller (Argo CD, Flux, a CI job) makes the runtime match it. Fast-forward-only guarantees production receives exactly the commit that was validated and approved — not a merge result nobody tested.

## Trade-offs
− No automatic rollback yet (a `git revert` of the fix commit is the manual path).

---

# Decision: D-23 No authentication in the MVP

Date: 2026-10-04
Status: Accepted (known risk)
Area: Security

## Context
Anyone who can reach the AION API can approve a patch by typing a name.

## Decision
No login in the MVP; AION binds to `127.0.0.1` by default. Every decision is recorded with the typed name in the audit trail.

## Reason
Authentication (OIDC/SSO, roles such as "approver") is well-understood infrastructure that does not demonstrate AION's core idea, and would add a large amount of setup for a local demo.

## Future Reconsideration
**First item after the MVP**: OIDC login, an `approver` role, and approvals bound to the authenticated identity; optionally require two approvers for production.

---

# Decision: D-24 Append-only audit table

Date: 2026-10-04
Status: Accepted
Area: Audit

## Decision
`audit_events(timestamp, incident_id, actor, action, details)`. Actors are namespaced: `system:<component>`, `ai:<provider:model>`, `human:<name>`. No API updates or deletes rows. All status changes are audited automatically inside `lifecycle.transition()`.

## Reason
Answers "who/what did what, when, and why" for every incident — including which actions were taken by an AI and which by a person.

## Future Reconsideration
Tamper evidence (hash-chaining each row to the previous one) or shipping audit events to write-once storage.

---

# Decision: D-25 A real demo service with synthetic git history

Date: 2026-10-04
Status: Accepted
Area: Demo

## Decision
`demo/orders-service-history/` holds 7 commit "overlays" by 4 fictional developers. `demo/demo_repo.py` builds a real git repository with backdated timestamps; commit 06 introduces a latent bug (expired coupons → `None` → `TypeError`) that the existing tests don't catch; commit 07 is an unrelated change in the same deployment (a realistic distractor). `demo/run_demo.py` registers the service, records deployments, runs it in "production" and sends traffic.

## Reason
AION needs something real to observe. Everything AION does with this repository — blame, diffs, worktrees, tests, staging, merge — is genuine; only the *history* is staged so the demo is reproducible.

---

# Decision: D-26 Intentionally NOT in the MVP

Date: 2026-10-04
Status: Accepted
Area: Scope

| Not implemented | Why not now | When |
|---|---|---|
| Container sandbox for running AI-generated code | Needs Docker images per service; local demo trusts its own machine | Before any shared/production use |
| Authentication / roles | See D-23 | First post-MVP item |
| Automatic rollback | Manual `git revert` path is clear; auto-rollback needs reliable health signals | After metrics-based detection |
| Non-Python stack traces | One language end-to-end first (D-01) | Post-MVP |
| Real CI (GitHub Actions) / real staging | Requires accounts/infrastructure; interface exists | Post-MVP |
| Metrics/traces as detection input | Logs are enough to demonstrate the workflow | Post-MVP |
| Vector search | Not needed for exact retrieval (D-13) | When runbooks/docs are added |
| Kubernetes, Kafka, microservices | No scaling need (D-02) | Only if scale demands it |
