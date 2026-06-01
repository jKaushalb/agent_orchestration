# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

The repo has two layers:

- **`agents_from_scratch/`** (formerly `src/`) — the origin prototype: a small, from-scratch multi-agent loop built directly on `litellm` (no agent SDK), with the agent topology hand-wired in code. Reference apps: a Writer/Critic article loop and a passport-OCR judge loop.
- **`agent_platform/`** — the product: a real platform built on the prototype's good ideas. Agent CRUD, a visual workflow builder, asynchronous agent-to-agent messaging over a DB-backed message bus, persisted + UI-visible history, schedules/memory/guardrails, and a Telegram channel. Runs locally from a single command.

A `venv/` is checked into the repo root (`agent_orchestration/venv/`) and already has both the prototype and platform dependencies installed.

## Environment & Commands

Activate the venv before running anything:

```powershell
.\venv\Scripts\Activate.ps1   # PowerShell
```

### The platform (`agent_platform/`)

```powershell
cd agent_platform
python run.py                 # builds the frontend (needs Node) + runs the whole app at :8000
python run.py --no-frontend   # API only; run `npm run dev` in frontend/ for hot-reload
```

`run.py` starts the FastAPI backend with the async orchestrator, the scheduler, and (if `TELEGRAM_BOT_TOKEN` is set) the Telegram channel, serves the built UI, and on first run **seeds** the Deep Research workflow. Secrets come from `agent_platform/.env` (see `.env.example`); `litellm` resolves model credentials by model-name prefix (e.g. `gemini/...` → `GEMINI_API_KEY`), and `TAVILY_API_KEY` enables the `web_search` tool.

Offline verification scripts (no LLM calls, run from `agent_platform/`):

```powershell
python -m backend.verify_crud          # agent CRUD endpoints
python -m backend.verify_orchestrator  # fan-out, join, feedback loop, termination
python -m backend.verify_config        # memory injection, guardrail redaction, schedule triggers
```

### The prototype (`agents_from_scratch/`)

```powershell
python agents_from_scratch/agents/runner.py            # the hand-wired orchestration
cd agents_from_scratch/agents; python agent.py         # single-agent image-analysis demo (__main__)
```

There is no test suite, linter, or build step for the prototype. `agents_from_scratch/agents/agents.ipynb` is the scratch notebook (gitignored).

## Architecture — `agent_platform/`

Separate, self-contained `backend/` (FastAPI) and `frontend/` (React + React Flow) projects; the frontend talks to the backend only over REST + SSE.

**The central idea is a DB-backed message bus.** Agents never call each other directly — they exchange rows in the `messages` table. One async worker claims `pending` messages, runs the recipient agent, and routes its output to downstream agents per the workflow graph's edges. That table is simultaneously the async transport, the persistence layer, and the UI feed.

Backend modules under `agent_platform/backend/`:

- **`models.py`** — SQLModel tables. `Agent` (every configurable dimension as a column; list/dict config in JSON columns), `Workflow` (`graph` = `{entry, nodes, edges}`), `Run` (status, `steps`, `max_steps` loop guard, `cost`, channel), `Message` (the bus row), `Memory`.
- **`runtime/`** — execution on `litellm`. `runner.run_agent(config, user_input, history)` runs the model with the agent's tools in a manual tool-use loop and returns `(output, cost)`. `tools.py` keeps the prototype's two-parallel-dict pattern (`TOOL_REGISTRY` + `TOOLS_TO_FUNCTION`); tools: `web_search` (Tavily), `web_search2` (DuckDuckGo), `wikipedia_extract`, `fetch_url`, and sandboxed `read_file`/`write_file`/`list_files` (confined to `backend/workspace/`).
- **`orchestrator.py`** — the async worker. Routing is data: fan-out (multiple edges out), **join** (edges marked `"join": true` act as a barrier), conditional edges (`{"contains": "...", "negate": bool}`), and feedback loops (edges pointing upstream, bounded by `Run.max_steps`). Also injects per-agent memory and enforces guardrails (`blocked_words` redaction, `max_cost_usd` cap, `allowed_recipients`).
- **`ingest.py`** — `create_run(...)`, the shared entry point used by both the HTTP route and Telegram.
- **`routes/`** — `agents` (CRUD), `messages` (`POST /runs`, `GET /messages`, SSE `GET /messages/stream`), `workflows` (CRUD). `main.py` also serves `/tools` and `/models`.
- **`channels/telegram.py`** — long-poll adapter; inbound text/images enter the bus via `ingest`, terminal output is pushed back to the chat. No-op unless `TELEGRAM_BOT_TOKEN` is set.
- **`scheduler.py`** — APScheduler; runs agents whose `schedule` is set, reloaded when agents change.
- **`seed.py`** — seeds the Lead + 3 Researchers + Writer + Critic agents and their workflow on first run.

Frontend under `agent_platform/frontend/src/`: `ChatPanel` (live SSE stream with agent labels, text + image input), `AgentsPanel` (full agent CRUD incl. model dropdown + custom id, and an Advanced section for schedule/memory/guardrails/skills), `WorkflowBuilder` (React Flow canvas → `graph_json`).

The platform was built in small, single-purpose commits (one per capability), each verified before the next, with **no AI attribution in commit messages**.

## Architecture — `agents_from_scratch/` (prototype)

Three layers, all under `agents_from_scratch/agents/`:

- **`agent.py`** — core abstractions. Pydantic config models (`AgentClientConfig`, `AgentConfig`, composed into `CreateAgent`/`UpdateAgent`) plus `BaseAgent`. `BaseAgent` owns the conversation `history`, accumulated `costs`, and tool definitions. It is provider-agnostic: `run()` takes a `completion` callable (passed in from the caller) rather than importing one, and dispatches to sync `_run` or async `_run_async`. Per-call cost is computed from `litellm.cost_per_token` rates captured at init.

- **`tools.py`** — the tool layer, driven by two parallel dicts that must stay aligned: `TOOL_REGISTRY` (OpenAI-style JSON schema sent to the model) and `TOOLS_to_FUNCTION` (name → Python callable). An agent's `config.tools` is a list of string keys into these dicts.

- **`runner.py`** — the hand-wired orchestration. `single_llm_call` is the manual tool-use loop: it injects tool definitions, calls the model, executes any returned tool call, appends the result via `add_tool_response`, and retries up to `max_try`.

### Message format

`history` follows the OpenAI chat schema. A system message (from `config.system_prompt`) is lazily prepended on the first `add_message`. `UserQuery` carries either a single `query`/`query_type` or parallel lists; `Query.IMAGE_URL` content is wrapped as a base64 data URL (`utils.encode_image` produces the base64 string).

### Known rough edges (prototype only)

These exist in `agents_from_scratch/` (the platform's `runtime/` is a clean re-port that fixes the tool bugs):

- `_run`/`_run_async` pass `max_competion_tokens` (typo for `max_completion_tokens`) to `litellm`.
- `run(async_execute=True)` returns an un-awaited coroutine, so cost accounting then fails.
- `TOOL_REGISTRY`: `wikipedia_extract` uses key `descrition` and places `required` outside `parameters`; `web_search2` ignores its `query` argument and hardcodes `"python programming"`. (Both fixed in `agent_platform/backend/runtime/tools.py`.)
- `runner.py` is inconsistent about passing `add_message`'s `query` positionally vs by keyword.
- `Literal["user", "assitant"]` and `max_itteration` contain typos that are referenced by name.

The `AI_*.md` files in `agents_from_scratch/agents/` are generated article outputs from prior runs (via the write tool), not source.
