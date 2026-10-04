# AION Evaluation

How well does AION actually work, and where does it fail? This document describes the method and the measured results. Raw results (tables + per-scenario details, including diffs and failing test output) are in [`evaluation/results/`](../evaluation/results/).

## Method

- **Scenarios** (`demo/scenarios/`): four realistic incidents on the demo `orders-service`, built on the same 5-commit base history, each with a **known answer** (the culprit commit, the exception type, or "no incident").

| Scenario | Bug | What it tests |
|---|---|---|
| `expired-coupon` | `TypeError`: expired coupon → `None` | culprit changed the crashing line |
| `supplier-feed` | `KeyError: 'price'`: new product uses `unit_price` | culprit changed only *data*; `git blame` points at innocent old code |
| `empty-cart-average` | `ZeroDivisionError` on an empty draft cart | a condition that was harmless for a day becomes fatal after a new feature |
| `healthy-release` | none | false-positive check: harmless release + background noise |

- **Harness** (`evaluation/run_eval.py`): for each scenario, a fresh temporary workspace and database; the git history is built; the real service code is executed to generate logs (normal traffic + trigger requests); logs are ingested through the API; the real pipeline runs (detection → correlation → RCA → patch → validation). Production deployment is not part of the evaluation (it always requires a human).
- **Metrics**: detection correct; rank of the true culprit in the correlation; whether the RCA names the true culprit; patch attempt sequence; validation; final status (reaching `awaiting_approval` = the automated part succeeded); time; tokens.
- **Modes**: `heuristic` (no LLM: correlation-ranked RCA + `git revert`) and `llm` (here: **qwen2.5-coder:7b, Q4_K_M, local via Ollama on an RTX 3050 6 GB**, 12k context).

Run it yourself:
```powershell
backend\.venv\Scripts\python evaluation\run_eval.py                 # heuristic
backend\.venv\Scripts\python evaluation\run_eval.py --mode llm      # model from backend\.env
```

## Results

### Final (current code)

| Mode | Detection correct | Culprit ranked #1 by correlation | RCA names culprit | Reached approval gate (or correctly silent) | Avg. time per incident |
|---|---|---|---|---|---|
| Heuristic (no LLM) — [results](../evaluation/results/20261004-2226-heuristic.md) | 4/4 | 3/3 | 3/3 | **4/4** | ~5 s |
| Local LLM qwen2.5-coder:7b — [results](../evaluation/results/20261004-2232-llm.md) | 4/4 | 3/3 | 2/3 | **3/4** | ~100 s |

Local-LLM detail (final run):

| Scenario | RCA | Patch attempts | Outcome |
|---|---|---|---|
| empty-cart-average | ✅ correct, confidence 0.9 | AI ✗ → AI ✗ → revert ✓ | awaiting approval |
| expired-coupon | ✅ correct, confidence 0.9 | AI ✗ → AI ✗ → revert ✓ | awaiting approval |
| supplier-feed | ❌ described the symptom, named no commit | AI ✗ → AI ✗ | validation failed → human |
| healthy-release | — | — | no incident (correct) |

### How we got there — what the evaluation exposed

| Run | Change since previous run | Heuristic: gate / RCA | Local LLM: gate / RCA | Key observation |
|---|---|---|---|---|
| 1 — [heuristic](../evaluation/results/20261004-1803-heuristic.md), [llm](../evaluation/results/20261004-1831-llm.md) | — (MVP code) | 3/4 · 2/3 | 1/4 · 2/3 | supplier-feed: blame points at old code (culprit ranked 3rd). **Every LLM patch failed the syntax check.** |
| 2 | dependency-overlap correlation signal; keyword signal restricted to the specific error; prompt guidance | **4/4 · 3/3** | — | culprit now ranked 1st in all scenarios |
| 3 — [llm](../evaluation/results/20261004-2217-llm.md) | indentation-only repair of edits (incl. search text without leading spaces) | — | 1/4 · 2/3 | patches now compile and their regression tests fail on the buggy code ✔ — but the fixes/tests are semantically wrong |
| 4 — [llm, 3 attempts](../evaluation/results/20261004-2224-llm.md) | 3 AI attempts instead of 2 | — | 1/4 · 2/3 | a third attempt does **not** help the 7B model |
| 5 — final | revert fallback after failed AI attempts | 4/4 · 3/3 | **3/4** · 2/3 | rollback rescues 2 incidents; still gated by validation + human |

### Why the local model's patches failed (all caught by validation)

| Scenario | What qwen2.5-coder:7b did | Caught by |
|---|---|---|
| empty-cart-average | **Correct fix**, but its regression test used order 1001 instead of the empty cart 1010 | its own test failed |
| expired-coupon | Guarded `coupon["percent"]` but still read `coupon["max_discount"]` on `None` | its own regression test crashed |
| supplier-feed | "Fixed" by silently pricing the product at 0 instead of reading `unit_price` | unit tests |

**No incorrect patch reached the approval gate in any run.**

## Conclusions (for the report / viva)

1. **Detection and correlation are strong and deterministic**: 4/4 detection with no false positive; after the evaluation-driven fixes the true culprit is ranked first in every incident scenario — including the one where blame points the wrong way (narrowly: 0.40 vs 0.40, tie broken by recency — reported honestly).
2. **A 7B local model is good at diagnosis, weak at repair.** It explained 3/3 root causes in plain language and named the right commit in 2/3, but none of its code fixes passed validation, and more attempts did not help. A stronger model (e.g. Claude) is expected to do much better; the evaluation is ready to measure it with one configuration change.
3. **The safety design works as intended**: every wrong patch was stopped by deterministic validation (syntax, the model's own regression test, the existing tests), and every remaining decision went to a human.
4. **Evaluation pays for itself**: it found four real weaknesses (indentation handling, keyword noise, a missing correlation signal, no rollback path) that one demo never would have.

## Limitations of this evaluation

- Small (4 scenarios), self-authored, one service, one language: it shows behaviour and failure modes, not general accuracy.
- One run per configuration; LLM outputs vary between runs (temperature 0.1). Repeated runs would give a distribution.
- Prompt guidance was adjusted after observing failures. To avoid overfitting, every change was **generic** (indentation, dependency signal, keyword noise, rollback) rather than scenario-specific, and each is covered by a unit test.
