# BalanceLoop — A One-Person AI Company for Reviewed Lifestyle Support

ELEC5620 (Model-Based Software Engineering) · Mon 17–19 Group 8 · **Stage 2 prototype**

BalanceLoop helps adults log meals and build low-intensity activity habits. One human **Founder** sets the
rules; four LLM-powered agents do the daily work and **nothing personalised reaches the user without passing
the Safety Supervisor**:

| Agent | Role | Use cases |
|---|---|---|
| **Orchestrator** | relays requests, reconciles diet + exercise into one daily plan, drives the review loop | UC01, UC09 |
| **Nutrition Coach** | records meals with traceable uncertainty, drafts and adapts diet plans | UC02, UC03, UC04 |
| **Fitness Coach** | assesses readiness, drafts and adapts exercise plans, records activity feedback | UC05–UC08 |
| **Safety Supervisor** | hard rules → explainable risk score → approve / revise / safe fallback / critical stop; audit | UC10 |

> Lifestyle support only — the system never diagnoses or treats a medical condition.

```
 user ──▶ Orchestrator ──┬──▶ Nutrition Coach ──┐  LLM drafts / interprets (DeepSeek via LLMGateway)
                         ├──▶ Fitness Coach ────┤  rules decide (rules/*.py)
                         └──▶ reconcile (UC09) ─┴──▶ Safety Supervisor (UC10) ──▶ release | safe response | stop
 founder ──▶ policy, incidents, audit replay           every step: AuditRecord + AgentTrace (AR-10)
```

## Repository layout

```
pyproject.toml · uv.lock · requirements.txt   Python project (root); .venv is created here by `uv sync`
dev.py                                        one-click: backend + frontend
backend/   FastAPI + SQLAlchemy + SQLite
  run_dev.py       backend-only entry point (IDE ▶)
  app/agents/      Agent base, Orchestrator, NutritionCoach, FitnessCoach, SafetySupervisor (class diagram Fig. 3)
  app/rules/       deterministic rules: readiness, hard rules, risk score R=2S+U+V+P+B, conflicts, load, punitive
  app/llm/         LLMGateway (structured JSON outputs) → CloudLLMClient (OpenAI-compatible) | MockLLMClient (offline)
  app/repository/  Repository interface → VersionedRecordStore (versioned records + audit log)
  app/external/    ExternalDataSource → local versioned nutrition table (nutrition-v1.0, 82 foods)
  app/db/models.py 20 tables, one per persistent class; status columns hold the state-machine states
  app/api/         REST endpoints (OpenAPI at /docs)
  tests/           40 rule unit tests + 20 end-to-end API scenarios (offline mock)
frontend/  Vue 3 + Vite + Element Plus — user app and Founder console
docs/      api.md · demo_script.md · agile/ (backlog, sprints, retrospectives)
```

## Quick start (clone → run in 5 minutes)

Prerequisites: **Python ≥ 3.11**, **Node.js ≥ 18**, and **uv** (`pip install uv` or `brew install uv`).

```bash
git clone <this-repository-url> BalanceLoop
cd BalanceLoop
uv sync                                  # Python env: creates ./.venv from pyproject.toml + uv.lock
cp backend/.env.example backend/.env     # settings; git-ignored
cd frontend && npm install && cd ..      # frontend packages
uv run python dev.py                     # backend http://localhost:8000 + frontend http://localhost:5173
```

Then open <http://localhost:5173>, pick a user in the top-right corner and start clicking:

| User | What you get |
|---|---|
| **Sam Lee** | a fully seeded demo: profile, yesterday's and today's check-ins, released exercise / diet / daily plans, meals, feedback — every page has data |
| **Alex Chen** | an empty account, to walk through consent and profile creation (UC01) from scratch |
| **Founder** | the operator console: review policies, incidents, audit replay |

**LLM**: `backend/.env` decides. `BL_LLM_PROVIDER=mock` (default in `.env.example`) runs fully offline with a
deterministic stand-in — nothing to configure. `BL_LLM_PROVIDER=cloud` uses any OpenAI-compatible chat API
(`BL_LLM_BASE_URL`, `BL_LLM_MODEL`, `BL_LLM_API_KEY`; DeepSeek, OpenAI or a self-hosted vLLM/Ollama/LiteLLM endpoint —
check the connection with `uv run python backend/llm_check.py`). Either way the model only drafts
or interprets — every safety decision is made by rules, and the pipeline drawer in the UI shows which is which.

Useful extras:

```bash
uv run pytest -q                                     # offline backend regression suite
curl -X POST http://localhost:8000/api/admin/reset-demo   # wipe + re-seed (?demo_flow=false for an empty day)
```

API docs: <http://localhost:8000/docs>. Demo walkthrough: [docs/demo_script.md](docs/demo_script.md).

### Cloud gateway contracts (offline)

Run `uv run pytest backend/tests/test_cloud_client.py -q` to exercise the real
`CloudLLMClient` with simulated HTTP responses, without an API key or network calls.
The cases cover request construction, schema validation, malformed provider envelopes,
empty content, timeouts, connection failures, HTTP errors (including 429), fenced JSON,
and compatibility fallback when a provider rejects `response_format`.

Transport/HTTP failures and invalid provider envelopes raise `LLMUnavailable` immediately
so callers can degrade safely. Invalid model JSON or schema mismatches get at most one
corrective retry. Disabling unsupported JSON mode can add one compatibility request
(at most three HTTP calls in a completion). Provider error bodies and validation input
values are excluded from public error messages. Failed sequential calls clear stale
`last_meta`; this shared diagnostic field is not a concurrency-safe request tracing API.

These tests establish gateway behavior, not real-model quality, latency, or safety accuracy.

### Request-level model tracing

Every agent gateway invocation appends an `llmCall` step to the request trace, on success
or failure. It is returned in the API trace and persisted with existing `AgentTrace`
records for `GET /api/founder/requests/{request_id}/replay`. Open **Show detail** in
the pipeline drawer to inspect the statistics. No database migration is needed.

Each span has a unique `call_id`, `request_id`, agent, operation, model version, status,
total `latency_ms`, `attempt_count`, `retry_count`, token `usage` and per-HTTP-attempt
timings/status codes. Retries count additional HTTP requests, including JSON-mode
compatibility fallback and schema correction; a retry's tokens are included in totals.
Each attempt also retains its own reported prompt/completion/total token counts.

Missing or invalid token counts are `null`, not zero. Totals sum available observations;
`usage_complete` marks each field false when any attempt omitted it. Mock calls are
explicitly marked and have zero HTTP attempts with unknown token usage. No prompts,
response text, credentials or provider error messages are copied into these metric spans.

Collectors use `ContextVar` isolation and request-owned traces, never the shared client's
`last_meta`. Tests cover concurrent requests sharing one cloud client, failed/retried
calls, exact clock-controlled timings, and API-to-database replay for success and failure.
Spans live in memory until the existing request trace save point; process crashes or
database failures before that point are not durable telemetry delivery guarantees.

### Configuration: `backend/.env`

All settings are read from **`backend/.env`** (exactly that name and location, next to `app/`). The file is
git-ignored, so each person creates their own copy — `cp backend/.env.example backend/.env` — and the
template already contains every key with a working offline default. Variable names are fixed; only the values change:

| Variable | Default (template) | Meaning / when to change it |
|---|---|---|
| `BL_LLM_PROVIDER` | `mock` | `mock` = offline deterministic stand-in (no key needed). `cloud` = call a real model. |
| `BL_LLM_BASE_URL` | `https://api.deepseek.com` | Base URL of any OpenAI-compatible server. `https://host`, `https://host/v1` and `…/v1/chat/completions` are all accepted. For a lecturer-provided or self-hosted endpoint put its address here. |
| `BL_LLM_MODEL` | `deepseek-chat` | Model name exactly as that server expects (e.g. `gpt-4o-mini`, `qwen2.5:7b`, or whatever the lecturer tells you). |
| `BL_LLM_API_KEY` | `sk-your-key-here` | The key for that server. Never commit it; never paste it into reports. |
| `BL_LLM_TIMEOUT_SECONDS` | `60` | Per-call timeout; raise it for slow self-hosted models. |
| `BL_REQUIRED_POLICY_VERSION` | `1.0` | Review-policy version the Safety Supervisor insists on; activating any other version in the Founder console makes the system fail closed (demo of UC10 2b). |
| `BL_DATABASE_URL` | `sqlite:///./balanceloop.db` | SQLite file (a relative path is resolved against `backend/`). Point it at MySQL later, e.g. `mysql+pymysql://user:pass@host/balanceloop`. |
| `BL_SEED_DEMO_FLOW` | `true` | On an empty database, seed Sam's two-day demo (plans, meals, feedback). Set `false` for an empty start. |
| `BL_CORS_ORIGINS` | `http://localhost:5173,…` | Allowed frontend origins; add one if you serve the UI from another host/port. |

Values can also be given as environment variables (same names), which override the file — handy for one-off
runs such as `BL_LLM_PROVIDER=mock uv run python dev.py`. After editing `.env`, restart the backend
(`dev.py` / `run_dev.py` reload on code changes, not on `.env` changes). Check what the running backend uses with
`GET http://localhost:8000/api/health`, and test a real endpoint with `uv run python backend/llm_check.py`.

### Alternative ways to run

* **Backend only**: `uv run python backend/run_dev.py` or `uv run uvicorn --app-dir backend app.main:app --reload --port 8000`.
* **Frontend only**: `cd frontend && npm run dev`.
* **Without uv**: `python3 -m pip install -r requirements.txt` (generated from `uv.lock`), then the same commands with `python3` instead of `uv run python`.
* **PyCharm**: open the `BalanceLoop` folder; PyCharm picks up `./.venv` (otherwise *Settings → Project → Python Interpreter → Add → Existing → `.venv/bin/python`*). Shared run configurations in the top-right selector: **Full stack (backend + frontend)**, **Backend (FastAPI)**, **Backend tests (pytest)**, **Frontend (npm dev)** (npm needs PyCharm Professional).
* `./run.sh setup | backend | frontend | all | test | reset` wraps the same commands.

### Managing Python dependencies

`pyproject.toml` + `uv.lock` are the source of truth. Add a package with `uv add <name>` (or `uv add --dev <name>`),
then regenerate the pip file and commit all three:

```bash
uv export --format requirements-txt --no-hashes --no-emit-project -o requirements.txt
```

After pulling someone else's dependency change, run `uv sync` again. Never commit `.venv/`, `node_modules/`, `backend/.env` or `*.db`.

## How the prototype meets the Stage 2 brief

| Brief | Where |
|---|---|
| Implements the Stage 1 design | every class of Fig. 3 is a module/table; UC01–UC10 main scenarios + safety extensions; state-machine states are the `status` enums ([enums.py](backend/app/domain/enums.py)) |
| LLM enhances **perception** | `identifyFood`, `assessReadiness`, `interpretRecoveryNotes`, `interpretConstraints`, `interpretFeedback` |
| LLM enhances **decision-making** (as drafts) | `generateDietCandidate`, `generateExerciseCandidate`, `proposeMinimalChange`, `proposeAdaptations`, `classifyConflict` |
| LLM enhances **interaction** | focused clarification questions, rationale/explanations, `draftRevisionInstructions` |
| Rules decide, not the model | [rules/](backend/app/rules) — readiness result, hard rules HR-01…HR-08, risk level, conflicts, load, non-punitive |
| Every reply shows the pipeline | `trace` in each response: agent, step, **LLM draft** vs **rule**, model version → frontend "agent pipeline" drawer |
| Auditability (AR-10) | `audit_records` written before a decision takes effect; Founder replay `GET /api/founder/requests/{id}/replay` |
| Fail-closed | policy missing/mismatched or audit store failing → non-personalised reply, incident for the Founder |
| Agile | [docs/agile](docs/agile) — backlog, 3 sprints, retrospectives; commits are tagged with use-case ids |

## Safety policy (prototype values, not clinical)

* **Hard rules** (policy v1.0): HR-01 allergen in meal · HR-02 pain ≥ 7 or red-flag symptom (*critical*) · HR-03 Recovery ignored ·
  HR-04 punitive/compensatory content · HR-05 allergy status unknown · HR-06 medical claims · HR-07 evidence/version outdated ·
  HR-08 self-harm / disordered-eating signs (*critical*).
* **Risk score** R = 2S + U + V + P + B (0–15): Critical ≥ 11 or critical rule · High if S = 3 or R 7–10 · Medium 4–6 · Low 0–3.
  Low → release exact version · Medium → rule-linked revision (max 2) · High → bounded safe response · Critical → support notice, incident, Founder.

## Team

Shun Lin · Yiheng Yang · Zixian Yu · Zhengzhao Chen · Haozhe Jiang — contributions per use case are listed in the Stage 1 report and in `docs/agile/product_backlog.md`.

## 中文快速开始

1. 安装 Python ≥ 3.11、Node.js ≥ 18，然后 `pip install uv`。
2. 克隆仓库后在根目录执行 `uv sync`（创建 `.venv` 并装好全部依赖），再 `cp backend/.env.example backend/.env`。
   配置文件必须叫 `backend/.env`。默认 `BL_LLM_PROVIDER=mock`，离线即可运行；
   要用真实模型，把它改成 `cloud`，并填 `BL_LLM_BASE_URL`（服务地址）、`BL_LLM_MODEL`（模型名）、`BL_LLM_API_KEY`（key）三项。
   全部变量的含义见上面的 Configuration 表；改完 `.env` 要重启后端，
   用 `uv run python backend/llm_check.py` 可以测连通。
3. `cd frontend && npm install && cd ..`。
4. `uv run python dev.py` 同时启动后端（:8000）和前端（:5173）；PyCharm 里选 **Full stack** 运行配置点 ▶ 也一样。
5. 浏览器打开 http://localhost:5173 ，右上角选 **Sam Lee**（已有完整演示数据）、**Alex Chen**（空账号，演示建档）或 **Founder**（运营控制台）。
6. 跑测试：`uv run pytest -q`。重置演示数据：`curl -X POST http://localhost:8000/api/admin/reset-demo`。

加依赖用 `uv add 包名`，然后执行上面的 `uv export …` 重新生成 `requirements.txt`，三个文件一起提交。`.venv`、`node_modules`、`backend/.env`、`*.db` 不要提交。
