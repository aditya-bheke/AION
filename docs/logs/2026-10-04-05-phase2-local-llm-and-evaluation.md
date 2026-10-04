# 05 — Phase 2 (in progress): local LLM, scenarios and evaluation

**Date:** 2026-10-04
**Task:** Run AION with a real (local, free) LLM; add more bug scenarios; build an evaluation harness.

## What changed
- **Local LLM on D:** LM Studio on this machine was a non-working leftover (its settings were pointed to D: and backed up as `settings.json.bak-before-D-drive`). Installed **portable Ollama 0.35.1** in `D:\Ollama` (nothing installed on C:), model `qwen2.5-coder:7b` (Q4_K_M, 4.7 GB) in `D:\Ollama\models` (`OLLAMA_MODELS` user env var). `scripts/setup-ollama.ps1`, `scripts/start-ollama.ps1`. `backend/.env` points AION at `http://127.0.0.1:11434/v1` (D-28).
- **Context window:** measured AION prompts — RCA ~5.6–6.9k tokens, patch ~3.1–3.3k. Ollama's default 4096 would silently truncate RCA prompts → started with `OLLAMA_CONTEXT_LENGTH=12288`; AION caps local output at 4096 (`AION_OPENAI_MAX_TOKENS`). OpenAI-compatible adapter now sends the schema as real JSON (was a Python dict repr).
- **Scenarios** (`demo/scenarios/`, D-27): `expired-coupon`, `supplier-feed` (culprit changed data, not the crashing line), `empty-cart-average`, `healthy-release` (no incident expected). `demo_repo.build_repo(..., scenario=)`, `run_demo.py --scenario/--list`. Test `tests/test_scenarios.py` keeps them valid.
- **Evaluation harness** `evaluation/run_eval.py --mode heuristic|llm`: isolated temp workspace per scenario, real pipeline, scores vs known answers, writes `evaluation/results/*.md|json`.

## Results so far
| Run | Detection | Reached approval gate / correctly silent | RCA named culprit |
|---|---|---|---|
| Heuristic, first run | 4/4 | 3/4 | 2/3 (supplier-feed wrong, low confidence 0.32, validation blocked the bad revert) |
| LLM (qwen2.5-coder:7b), first run | 4/4 | 1/4 | 2/3 — **every LLM patch failed the syntax check** |
| Heuristic, after fixes below | 4/4 | **4/4** | **3/3** |
| LLM, after fixes | *not yet run* | | |

## Problems found by the evaluation, and generic fixes
1. **Small model lost relative indentation in `replace` blocks** (correct intent, invalid Python). → Indentation-only repair in `remediation/apply.py`: only when an exact edit turns a parseable file into a non-parseable one, re-indented variants are tried and the first that parses is kept; recorded in the patch rationale ("Applied by AION: …"). Tests added.
2. **Correlation missed causes off the stack** (supplier-feed). → New signal *dependency overlap* (0.15): commit changed a module imported by the failing code (Python imports resolved with `ast`). Test added.
3. **Keyword signal noise**: generic wrapper text ("Unhandled exception while processing request") and outer middleware frames gave an unrelated logging commit points. → keywords now come only from the exception title and the innermost 3 frames.
4. Prompt guidance (generic): RCA rule 4b (old failing line ⇒ look at recent changes to its inputs); patch rules on exact indentation and handling the bad value everywhere in the function.

Note: on supplier-feed the culprit now ranks first only narrowly (0.40 vs 0.40, tie broken by recency) — reported honestly; the LLM must confirm from the diffs.

## Tests
41 backend tests passing.

## Status / next steps (resume here)
1. Start Ollama: `powershell -ExecutionPolicy Bypass -File scripts\start-ollama.ps1` (keep open).
2. Re-run `backend\.venv\Scripts\python evaluation\run_eval.py --mode llm` (~6–8 min) and inspect failures (`patch_diff`, `failed_step` in the JSON).
3. Write `docs/EVALUATION.md` (method + before/after tables), update PROJECT_STATUS, notes (local), and run the live demo once in LLM mode.
