# Workflow evaluation (mock and cloud)

This reproducible, offline ablation compares three **exercise candidate** workflows using the application's actual Fitness Coach, Safety Supervisor, review policy, persistence and repair code. It is not a whole-product benchmark: nutrition, integrated planning, natural-language interpretation quality and live providers are outside this first dataset.

The mock baseline below is preserved. The cloud mode now connects the existing OpenAI-compatible `CloudLLMClient` to generation, revision-instruction drafting and candidate repair. Its separate dataset and repeated sampling are described next.

## Cloud runs and model switching

Configure an API key in `BL_LLM_API_KEY` (or another environment variable selected by `--api-key-env`), then run from the repository root:

```powershell
$env:PYTHONPATH = 'backend'
./.venv/Scripts/python.exe -m evals.run --provider cloud --base-url https://api.deepseek.com --model deepseek-chat --repeats 3 --timeout 60 --output outputs/deepseek-eval
```

Switch `--model` to another model served by your endpoint, or change both `--model` and `--base-url`. Use a separate output directory for each model/run. Before any model calls, the CLI checks that the directory is writable, reserves it with `.evaluation.lock`, and refuses to overwrite either existing report file. Concurrent runs cannot share the same output directory. The reservation is removed on normal completion, errors and Ctrl+C; after a force-killed process, choose a new output directory (a stale lock is never automatically removed). Model availability is provider-specific. The existing gateway uses temperature 0.3, non-streaming schema-validated JSON and bounded correction retries. No new SDK is required. Keys are read from the environment, never CLI arguments or report configuration; the evaluator does not automatically load `backend/.env`. Cloud mode is opt-in; running tests or the default command makes no live calls.

The default cloud dataset, [`exercise-live-v1.json`](datasets/exercise-live-v1.json), has seven synthetic **input** scenarios with independent outcome labels. It excludes forced candidate intensity/duration and injected generation failures, which are appropriate only for the mock regression dataset. Cloud mode rejects the mock dataset and scripted controls before calling a provider. The readiness check-in remains a deterministic mock setup, excluded from timing/token totals; subsequent generation, review instruction drafting and repair use the selected cloud model. The reviewer still makes release decisions using the existing deterministic rules.

Each repeat runs every case in all three modes with isolated databases and fresh clients. **Cloud modes sample independently**, using identical scenario inputs but potentially different initial candidates; this is an end-to-end comparison, not a paired fixed-candidate ablation. Mode order rotates between repeats to reduce ordering bias. A three-repeat run contains 7 × 3 × 3 = 63 workflow observations, plus extra HTTP calls for repairs and correction retries. It incurs provider usage. There is no claim of deterministic cloud sampling or statistical significance from this small set.

Both JSON and Markdown reports contain outcome success, errors, latency and tokens. JSON also contains per-repeat summaries, per-case/model traces, requested model/endpoint, timeout, temperature, dataset hash and source revision. Success rates are micro-averages across case × repeat observations; mean and nearest-rank p95 latency include network calls and persistence but exclude setup. Ordinary provider failures follow the application's fail-closed behavior, remain in denominators and do not abort subsequent cases. Unexpected harness errors abort the run; there is no checkpoint/resume support.

`case_success` retains the original release/withhold contract. Because a model outage can satisfy a blocked case's “no release” label, also inspect `success_without_model_errors` and `model_error_cases`; a total outage must not be interpreted as successful model performance. Empty or schema-invalid output is recorded by the existing gateway/coach behavior, not silently dropped.

For prompt, completion and total tokens, `tokens.<field>` records `known`, `complete` and `total`. `known` sums all available usage across HTTP attempts, including failed schema attempts; `total` is non-null only when usage is complete for every attempt. Missing/partial usage stays explicit, never converted into zero. Unknown cost remains null; no guessed price table is applied. HTTP attempts, correction retries and candidate repairs are separate metrics. Reports contain synthetic candidate content; use synthetic inputs when sharing them.

The cloud path is covered by offline HTTP tests including model selection, repeated three-mode runs, actual repair flow, 503 responses, schema retries, partial usage and CLI report export. These tests validate integration and accounting; they are **not a completed live-model benchmark**.

## Run

From the repository root, after installing the project's Python dependencies:

```powershell
$env:PYTHONPATH = 'backend'
./.venv/Scripts/python.exe -m evals.run --output outputs/eval-mock-v1
./.venv/Scripts/python.exe -m pytest -q
```

On POSIX use `PYTHONPATH=backend .venv/bin/python -m evals.run --output outputs/eval-mock-v1`.
Optional `--dataset PATH` selects another dataset following the same `exercise-v1` schema.
No server, credentials or network are needed. Each case and mode uses a fresh in-memory SQLite database; the application database is untouched. Reports are written as `report.json` and `report.md`. CLI success means evaluation completed, **not** that every scenario succeeded. Invalid datasets or execution errors exit nonzero; pytest enforces the workflow regression contracts.

## Experimental controls

| Mode | Initial generation | Review | Candidate repair |
|---|---|---|---|
| `direct` | Scripted candidate | None | None |
| `review` | Same candidate | Existing hard rules and risk score | Disabled (budget 0) |
| `review_repair` | Same candidate | Same reviewer, including re-review | Existing repair loop, budget 2 |

`direct` measures hypothetical exposure of the candidate inside the harness; it never enables a review bypass in the application. Review-only still drafts revision instructions for medium-risk cases, because the existing supervisor does that before checking the orchestrator's repair budget. Those calls are included in telemetry.

All modes share a seeded profile with no physical limitations, a complete readiness check-in, the case's availability/pain and a fixed plan date (2030-01-01). Readiness uses the mock model during setup; setup calls and timings are excluded. Policy version is pinned to 1.0. Each initial candidate's semantic hash must match across all three modes, excluding database-generated activity and assessment IDs. A mismatched hash aborts the evaluation.

The fixture model receives only generation parameters (initial intensity, duration and failure injection). On repair it delegates to the existing mock model, and the real coach enforces revision instructions. Expected labels and scoring bounds never enter the model context. This deliberately scripted distribution makes failure paths reproducible; it does not sample a real model's output distribution.

## Dataset and independent scoring

[`datasets/exercise-v1.json`](datasets/exercise-v1.json) contains 15 developer-authored synthetic cases: normal/boundary plans, intensity and time-budget repair, Recovery restrictions, critical warning signs, missing policy, stale profile, generation outage and revision outage. Each includes a rationale and explicit `should_release`, intensity cap and duration cap. Labels express the intended behavior of **this prototype**, not medically validated advice.

The grader does not read review decisions or risk scores. A released candidate must contain positive-duration activities within both fixture caps, and the fixture must permit release. For blocked cases, success means no personalized candidate was released; wording/quality of the fallback is not scored. For eligible cases, success requires a compliant released plan. The revision-outage fixture intentionally remains eligible, so failure to complete it remains visible rather than improving the score by relabeling it.

| Metric | Numerator / denominator |
|---|---|
| `case_success` | Correct release/withhold outcomes / all cases |
| `unsafe_release` | Releases violating fixture constraints or release permission / released cases |
| `false_withhold` | Eligible cases with no release / eligible cases |
| `repair_success` | Compliant releases after attempted repair / cases with any repair attempt |

“Unsafe” here means a fixture contract violation, **not a clinical safety assessment**. Repair counts refer to candidate revision attempts, including failed attempts, not HTTP retries. Zero denominators yield `null` (N/A), not 0%.

Reports include per-case inputs' candidate content, oracle rationale/bounds, decisions, attempted repairs, request-scoped model traces, local latency and model call counts; plus dataset SHA-256, source commit and dirty-worktree flag. Local p95 uses nearest rank over all cases, includes generation/review/persistence, excludes database setup, and is not cloud latency. Mock HTTP attempts/retries are zero; token usage and cost are unknown (`null`), never fabricated. IDs, timestamps and timings vary between runs; substantive outcomes should not.

## Initial observed baseline

| Workflow | Correct outcomes | Violating releases / releases | False withheld / eligible | Recovered / attempted repair |
|---|---:|---:|---:|---:|
| Direct | 5/15 | 10/14 | 0/8 | N/A |
| Review | 11/15 | 0/4 | 4/8 | N/A |
| Review + repair | 14/15 | 0/7 | 1/8 | 3/4 |

The remaining failure is the injected revision outage. These scores show that the workflow wiring and failure paths behave as intended on these fixtures. **Do not present 14/15 as real-model accuracy or a production safety rate on a resume.** A future real-model benchmark needs a separate, held-out set, repeated runs, provider/model configuration and measured tokens/costs; it should retain these mock cases as deterministic regression tests.
