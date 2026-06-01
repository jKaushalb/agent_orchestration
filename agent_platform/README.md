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

It runs real agents making real tool calls, so a full report (six agents plus a
critic loop) typically takes a few minutes — watch the messages stream in live.
For an instant smoke test, chat with a single agent directly (right panel →
pick an agent) instead of the whole workflow.

## Layout

```
agent_platform/
├── run.py            # single command: starts backend (+ frontend)
├── .env.example      # provider keys + Telegram token template
├── backend/          # FastAPI + SQLite + runtime + orchestrator (own requirements.txt)
└── frontend/         # React + React Flow (own package.json)
```

## Quick start (single command)

```powershell
cd agent_platform
pip install -r backend/requirements.txt   # one-time
copy .env.example .env                     # fill in keys (GEMINI_API_KEY etc.)
python run.py                              # builds the UI + runs everything
```

`run.py` builds the frontend (needs Node) and starts the backend — orchestrator,
scheduler, and Telegram (if a token is set) — serving the whole app at
**http://localhost:8000**. On first run it seeds the **Deep Research Assistant**
workflow so you can try it immediately. `/docs` has the interactive API.

For frontend hot-reload during development, run the API with
`python run.py --no-frontend` and the Vite dev server with `npm run dev` in
`frontend/` (it proxies to the backend).

## Verify it works

Each layer has a self-contained check (no UI needed):

```powershell
python -m backend.verify_crud          # agent CRUD
python -m backend.verify_orchestrator  # fan-out, join, feedback loop, termination
python -m backend.verify_config        # memory, guardrails, schedules
```

## Impact metrics → where they show up

- **Configurable dimensions per agent:** every column on the `Agent` row
  (identity, behaviour, tools, skills, channels, schedule, memory, interaction
  rules, guardrails) — all editable in the form.
- **Zero → working multi-agent workflow:** seeded on first run; or build one in
  the visual editor in minutes.
- **End-to-end completion / agent-to-agent reliability:** every hop is a
  persisted `messages` row with a status, and `Run` tracks steps + cost.

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

## Runtime & tools

The runtime (`backend/runtime/`) executes agent logic on top of `litellm`:
`run_agent(config, user_input, history)` runs the model, executes any tool
calls in a manual loop, and returns the final text + per-call cost.

Tool catalog (an agent's `tools` field selects from these):

| Tool | What it does |
|---|---|
| `web_search` | Web search via Tavily (needs `TAVILY_API_KEY`) |
| `web_search2` | Web search via DuckDuckGo (no key) |
| `wikipedia_extract` | Wikipedia summary + first sections |
| `fetch_url` | Fetch a page and return cleaned readable text |
| `write_file` / `read_file` / `list_files` | Read/write files in a sandboxed `workspace/` |

## Message bus & orchestration

Agents never call each other directly — they exchange rows in the `messages`
table. A single async worker (`backend/orchestrator.py`) claims `pending`
messages, runs the recipient agent, and routes its output to downstream agents
per the workflow graph's edges. That one table is the **async transport**
(a sender only writes a row, never awaits the receiver), the **persistence
layer**, and the **UI feed** — no Redis/Celery needed.

Routing is data, so every topology is just an edge set:

- **fan-out** — multiple edges out of one node (Lead → Researcher 1/2/3)
- **join** — edges marked `"join": true` into a node act as a barrier; the
  node fires once, with all inputs merged (Researchers → Writer)
- **conditions** — an edge fires only if its `condition` matches the output,
  e.g. `{"contains": "approved"}` or the same with `"negate": true`
- **feedback loops** — an edge can point back upstream (Critic → Writer); the
  run's `max_steps` guarantees termination

Start a run with `POST /runs`; read history with `GET /messages?run_id=...`;
stream it live with `GET /messages/stream?run_id=...` (SSE). The routing engine
is verified end-to-end (fan-out, join, loop, termination) by
`python -m backend.verify_orchestrator`.

## Web UI

`frontend/` is a React + Vite app (separate project, talks to the backend over
REST + SSE only):

- **Left — chat:** a CrewAI-style stream. Pick a target (a workflow or a single
  agent), send text or an uploaded image, and watch every agent's message stream
  in live with a colour-coded label. Backed by the persisted `messages` table,
  so history survives reloads.
- **Right — agents:** create / edit / delete agents and all their config
  (model, prompt, temperature, tools, channels). The model field is a dropdown
  of presets (Gemini 2.5 Flash/Pro, Gemini 3.5 Flash, Claude Sonnet/Opus, GPT-4o)
  with a **Custom…** option to type any litellm model id — litellm resolves the
  provider from the name prefix.

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173 (API calls proxied to :8000)
```

## Agent configuration (schedules · memory · guardrails)

Beyond model/prompt/tools/channels, each agent has (editable in the form's
**Advanced** section, enforced by the orchestrator):

- **Schedule** — a cron spec + prompt; APScheduler starts a run automatically on
  that cadence (e.g. a daily digest). Jobs reload whenever agents change.
- **Memory** — when enabled, the agent's recent exchanges are stored and
  re-injected as context on its next turn (`max_items` cap).
- **Guardrails** — `max_cost_usd` stops a run once its accumulated cost exceeds
  the cap; `blocked_words` redacts any output containing a disallowed term.
- **Interaction rules** — `allowed_recipients` restricts which agents a given
  agent may route to (API-configurable).

Verified by `python -m backend.verify_config` (memory injection, guardrail
redaction, schedule-trigger parsing).

## Telegram channel

An inbound Telegram message enters the **same message bus** as the web UI, and
terminal agent output is pushed back to the chat — so one agent/workflow is
reachable from both web and Telegram, with shared, persisted history.

- **Long polling** → no public URL, no webhook, no business approval; runs fully
  local. Enabled only when `TELEGRAM_BOT_TOKEN` is set (otherwise a silent
  no-op).
- Text **and** images are supported (a photo is base64-encoded into the run).
- Entry point: `TELEGRAM_ENTRY_WORKFLOW` (a workflow id) or
  `TELEGRAM_ENTRY_AGENT` (an agent id); defaults to the first workflow, else the
  first agent.

Setup: create a bot with [@BotFather](https://t.me/BotFather), put the token in
`.env`, restart, and message the bot.


