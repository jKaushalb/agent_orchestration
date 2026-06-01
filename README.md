# Multi-Agent Platform

Create AI agents, give each one a role, model, tools and guardrails, then wire
them together on a canvas and watch them **collaborate** — researching,
critiquing and revising each other's work — from a web chat or from Telegram.

This repository tells that story in two layers:

- **`agents_from_scratch/`** — the origin. A small, from-scratch multi-agent
  loop built directly on `litellm` (no agent SDK), where the agent topology was
  hand-wired in code. It proved the core ideas: a provider-agnostic agent with
  tool-calling and cost tracking, and a manual tool-use loop.
- **`agent_platform/`** — the product. A real platform that keeps those good
  ideas but replaces the hardcoded wiring with a data-driven engine: agent CRUD,
  a visual workflow builder, asynchronous agent-to-agent messaging, persisted
  history, schedules, memory, guardrails, and a Telegram channel — all running
  locally from a single command.

---

## The idea in one picture

Agents never call each other directly. They drop a message in a shared table,
and a single async worker delivers it to the next agent according to a graph you
draw. That one decision is the whole platform:

```
        you (web / telegram)
                 │  writes a row
                 ▼
        ┌──────────────────┐      claims rows, runs the
        │  messages table  │◀───  recipient agent, writes
        └──────────────────┘      its replies as new rows
                 ▲  routes by              │
                 │  graph edges            ▼
        ┌──────────────────┐      ┌──────────────────┐
        │ workflow graph   │      │  agent runtime    │
        │ (nodes + edges)  │      │  (litellm + tools)│
        └──────────────────┘      └──────────────────┘
```

Because routing lives in **data** (graph edges), not code, the same engine runs
any shape: a flat mesh where ten agents all talk to each other, or a manager
with a crew of workers, or a pipeline with a feedback loop — you change the
edges, not the program.

## The flagship demo — a Deep Research Assistant

```
You ─▶ Lead ─┬▶ Researcher 1 ─┐
             ├▶ Researcher 2 ─┤▶ Writer ─▶ Critic
             └▶ Researcher 3 ─┘     ▲          │
                                    └──loop─────┘   (until "approved")
```

A **Lead** breaks your question into sub-topics and fans it out to three
**Researchers** that run in parallel, each calling real web-search and
Wikipedia tools. Their findings **join** into a **Writer**, which drafts an
article. A **Critic** reviews it and either sends specific feedback back to the
Writer (a feedback loop) or approves it — at which point the final report is
delivered to you and saved. This single workflow demonstrates every capability:
parallel fan-out and join, real tool use, conditional routing, a feedback loop
that always terminates, persisted history, and delivery over a chat channel.

---

## How it works

### Agents are configuration
An agent is a single row of settings — its name and role, its model and prompt,
the tools and skills it has, the channels it answers on, an optional schedule,
its memory policy, and its guardrails. Everything about an agent's behaviour is
data you can edit in a form; nothing is hardcoded. Models are chosen per agent
(presets for Gemini, Claude and GPT, or any custom `litellm` model id), so each
agent can run on the model that suits it.

### Workflows are graphs
The visual builder is a canvas of agent nodes connected by edges. An edge can
carry a **condition** ("only follow this edge if the output contains
*approved*", optionally negated) and can be marked as a **join** so a node waits
for several inputs before firing. Edges may point backwards to form **feedback
loops**; a per-run step cap guarantees they always terminate. The graph you draw
is saved as JSON and is exactly what the orchestrator reads to route messages.

### The runtime actually runs
Each agent turn is executed on `litellm`: the model is called with the agent's
tools, any tool calls are run in a loop, and the cost of the call is tracked.
Tools include web search (two providers), Wikipedia, full-page fetch, and
sandboxed file read/write — so agents do real work, not a mockup.

### Everything is asynchronous and remembered
The message table is simultaneously the transport (a sender never waits on a
receiver), the database (every hop is a persisted row with a status), and the
live feed the UI streams. History survives restarts and is visible end-to-end.

### Two front doors, one bus
The same agent or workflow is reachable from the web chat and from Telegram.
A Telegram message enters the identical message bus and its answer is delivered
back to the chat, sharing the same persisted history.

---

## Decisions, and why

| Decision | Choice | Why |
|---|---|---|
| Agent runtime | **Custom, on `litellm`** | A working, provider-agnostic runtime already existed in `agents_from_scratch`. Adopting LangGraph/CrewAI would mean a rewrite for marginal gain and SDK lock-in. It is isolated behind one adapter, so it stays swappable. |
| Agent-to-agent transport | **A database table as a message bus** | One table is the async transport, the persistence layer, **and** the UI feed — three requirements satisfied by one decision, with no Redis/Celery/RabbitMQ to run or deploy. |
| Topology | **Data, not code** | Routing is graph edges + message rows, so mesh, manager/crew and feedback loops are just different edge sets. The engine never changes. |
| Persistence | **SQLite** | A single file with zero setup, so the whole thing runs locally from one command. |
| Backend | **FastAPI** | Async-native, matching `litellm`'s async client and the polling orchestrator. |
| Frontend | **React + React Flow** | React Flow gives a real node-graph editor for free; it's a separate project that talks to the backend only over REST + SSE. |
| Channel | **Telegram (long polling)** | No public URL, no webhook, no business approval — the only mainstream chat channel that runs truly locally. |
| Model | **Per-agent via `litellm`** | Any provider, selected by model-name prefix, chosen independently for each agent. |

---

## Repository layout

```
.
├── agents_from_scratch/   # the original from-scratch prototype (litellm, hand-wired)
│   └── agents/            # agent.py · tools.py · runner.py · utils.py
└── agent_platform/        # the platform
    ├── backend/           # FastAPI · SQLite · runtime · orchestrator · channels
    └── frontend/          # React + React Flow (chat, agent CRUD, workflow builder)
```

The platform was built incrementally — one small, self-contained commit per
capability (scaffold → agent CRUD → runtime → orchestrator → UI → Telegram →
visual builder → schedules/memory/guardrails → demo), each verified before the
next. Run instructions and per-feature detail live in
[`agent_platform/README.md`](agent_platform/README.md).

