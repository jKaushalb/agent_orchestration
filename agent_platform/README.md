# Agent Platform

A local-first **multi-agent orchestration platform**: create agents, wire them
into a visual workflow with conditions and feedback loops, and watch them
collaborate asynchronously — over a web chat **and** Telegram. The flagship demo
is a **Deep Research Assistant** (a Lead agent fans research out to several
Researcher agents, a Writer synthesizes, a Critic loops until the report is
approved).

> Built from scratch on top of `litellm` — no agent SDK. It reuses the clean
> abstractions from the `agent_orchestration` prototype (`BaseAgent`, the
> tool-registry pattern, `encode_image`) and replaces the prototype's hardcoded
> `runner.py` with a real, data-driven orchestrator.

## Why these choices (justification)

| Decision | Choice | Why |
|---|---|---|
| Agent runtime | **Custom, on `litellm`** | A working, provider-agnostic runtime with tool-calling + cost tracking already exists in the prototype. LangGraph/CrewAI would mean a rewrite for marginal gain and SDK lock-in. The runtime is isolated behind one adapter, so it stays swappable. |
| Agent ↔ agent transport | **DB-backed message bus** (one `messages` table) | A single table is the async transport (sender writes a row, never blocks the receiver), the persistence layer, **and** the UI feed — three requirements from one decision, with no Redis/Celery/RabbitMQ to run. |
| Topology | **Data, not code** | Routing comes from workflow-graph edges + message rows. Mesh ("10 agents talk to all") and master/worker ("1 master + 5 workers") are just different edge sets — no code changes. |
| Persistence | **SQLite** (SQLModel) | One file, zero setup → runs fully local with a single command. |
| Backend | **FastAPI** | Async-native, matches `litellm`'s async client. |
| Frontend | **React + React Flow** | React Flow gives the visual workflow builder for free. Separate project, talks to the backend only over REST + SSE. |
| Channel | **Telegram** (long polling) | No public URL, no business approval, works behind NAT — the only channel that runs truly local with one command. |
| Model | **Per-agent via `litellm`** | Any provider by model-name prefix (e.g. `gemini/...`). Model is an Agent field, so this is inherent. |

## Demo — Deep Research Assistant

```
User Q ─▶ Lead ─┬▶ Researcher 1 ─┐
                ├▶ Researcher 2 ─┤▶ Writer ─▶ Critic
                └▶ Researcher 3 ─┘     ▲          │
                                       └──loop─────┘   (until "approved")
```

This single workflow exercises every requirement: master/worker topology,
async parallel fan-out + join, real tool use (web search, Wikipedia, URL fetch),
a feedback loop with an edge condition, a chat channel, and persisted history.

## Layout

```
agent_platform/
├── run.py            # single command: starts backend (+ frontend)
├── .env.example      # provider keys + Telegram token template
├── backend/          # FastAPI + SQLite + runtime + orchestrator (own requirements.txt)
└── frontend/         # React + React Flow (own package.json)
```

## Quick start

```powershell
# 1. backend deps
cd agent_platform/backend ; pip install -r requirements.txt
# 2. copy env template and fill keys
copy ..\.env.example ..\.env
# 3. run everything
cd .. ; python run.py
```

Open http://localhost:8000/docs — interactive API docs. The web UI arrives in a
later chunk.

## API — Agents

Every agent is one row whose columns are the configurable dimensions (an impact
metric): identity (`name`, `role`), behaviour (`system_prompt`, `model`,
`temperature`, `max_output_tokens`, `thinking`), capabilities (`tools`,
`skills`), connectivity (`channels`), automation (`schedule`), state
(`memory_config`), and safety (`interaction_rules`, `guardrails`).

| Method | Path | Purpose |
|---|---|---|
| POST | `/agents` | create an agent |
| GET | `/agents` | list agents |
| GET | `/agents/{id}` | read one |
| PUT | `/agents/{id}` | partial update |
| DELETE | `/agents/{id}` | delete |

Smoke-test the API: `python -m backend.verify_crud` (from `agent_platform/`).

## Build status

Built in small, committed chunks (see `../../plan.md`). Done: **Chunk 0**
(scaffold + decisions), **Chunk 1** (agent CRUD backend).


