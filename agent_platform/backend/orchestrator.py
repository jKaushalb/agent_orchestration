"""Async message-bus orchestrator.

A single background asyncio task drives the whole platform:

  1. claim ``pending`` messages whose ``recipient`` is an agent,
  2. run that agent (in a thread, since litellm is sync) on the message content,
  3. route the agent's output to downstream agents per the workflow graph's
     edges + conditions — creating new ``pending`` messages,
  4. mark the input message ``done`` and bump the run's step counter.

Because routing is data (graph edges), the same engine handles mesh,
master/worker, fan-out, join and feedback loops. ``Run.max_steps`` guarantees
loops terminate. Agent-to-agent communication is therefore asynchronous (a
sender only ever writes a row; it never awaits the receiver) and fully
persisted (every row is history the UI can read).
"""
import asyncio
import logging
import traceback
from typing import Any, Callable, Dict, List, Optional

from sqlmodel import Session, select

from .db import engine
from .models import Agent, Memory, Message, Run, Workflow
from .runtime.runner import AgentRunConfig, run_agent

logger = logging.getLogger("agent_platform.orchestrator")


# The agent-execution function: (config, content, history) -> RunResult-like.
# Tests override this with a fake to avoid LLM calls.
RunFn = Callable[..., Any]


class Orchestrator:
    def __init__(self, run_fn: RunFn = run_agent, poll_interval: float = 0.4):
        self._run_fn = run_fn
        self._poll = poll_interval
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        # join buffers: (run_id, target_agent_id) -> {source_agent_id: content}
        self._joins: Dict[tuple, Dict[str, str]] = {}

    # --- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def _loop(self) -> None:
        while not self._stop.is_set():
            claimed = self._claim_pending()
            if claimed:
                await asyncio.gather(*(self._handle(m) for m in claimed))
            else:
                await asyncio.sleep(self._poll)

    # --- claim --------------------------------------------------------------
    def _claim_pending(self) -> List[dict]:
        """Atomically flip pending agent-bound messages to processing."""
        out: List[dict] = []
        with Session(engine) as s:
            rows = s.exec(
                select(Message).where(Message.status == "pending")
            ).all()
            for m in rows:
                if not m.recipient or m.recipient == "user":
                    # terminal/user-facing: nothing to execute, just settle it.
                    m.status = "done"
                    s.add(m)
                    continue
                m.status = "processing"
                s.add(m)
                out.append(
                    {"id": m.id, "run_id": m.run_id, "recipient": m.recipient,
                     "content": m.content}
                )
            s.commit()
        return out

    # --- handle one message -------------------------------------------------
    async def _handle(self, m: dict) -> None:
        run, agent = self._load(m["run_id"], m["recipient"])
        if run is None or run.status != "running":
            self._settle(m["id"], "done")
            return
        if agent is None:
            self._settle(m["id"], "failed", error=f"unknown agent {m['recipient']}")
            return
        if run.steps >= run.max_steps:
            self._finish_run(run.id, "completed")
            self._settle(m["id"], "done")
            return

        cfg = AgentRunConfig.from_row(agent)
        # Broader context: cross-run memory (if enabled) + this run's transcript so
        # far, so each agent sees the actual artifacts (e.g. the Writer's draft),
        # not just the single previous message.
        history = (self._load_memory(agent) or []) + self._run_transcript(run.id, m["id"])
        history = history or None
        try:
            result = await asyncio.to_thread(self._run_fn, cfg, m["content"], history)
            output = result.output if hasattr(result, "output") else str(result)
            cost = getattr(result, "cost", 0.0)
        except Exception as e:  # agent failed -> log it, surface it, end the run
            err = f"{type(e).__name__}: {e}"
            logger.error("agent '%s' failed in run %s: %s", agent.name, run.id, err)
            traceback.print_exc()
            self._settle(m["id"], "failed", error=err)
            # Make the failure visible in the UI / channel instead of hanging.
            self._emit_raw(run.id, sender=agent.id, label=f"{agent.name} (error)",
                           content=f"{agent.name} failed: {err}", recipient="user",
                           status="done")
            self._finish_run(run.id, "failed")
            return

        # The run may have been stopped while this agent was working — if so,
        # record nothing downstream and settle quietly.
        if self._run_status(run.id) != "running":
            self._settle(m["id"], "done")
            return

        # Guardrail: redact output containing blocked words.
        output = _apply_output_guardrails(agent, output)
        self._save_memory(agent, m["content"], output)
        run_cost = self._bump_steps(run.id, cost)
        self._route(run, agent, output, cost)
        self._settle(m["id"], "done")

        # Guardrail: stop the run once it exceeds its cost cap.
        cap = (agent.guardrails or {}).get("max_cost_usd")
        if cap is not None and run_cost >= cap:
            self._finish_run(run.id, "completed")

    # --- routing ------------------------------------------------------------
    def _route(self, run: Run, agent: Agent, output: str, cost: float) -> None:
        graph = self._graph(run.workflow_id)
        edges = [e for e in graph.get("edges", []) if e.get("source") == agent.id]

        # No outgoing edges -> deliver to the user and complete the run.
        if not edges:
            self._emit(run.id, agent, output, recipient="user", status="done")
            self._finish_run(run.id, "completed")
            return

        targets = [e for e in edges if _passes(e.get("condition"), output)]

        # Guardrail / interaction rule: restrict who this agent may message.
        allowed = (agent.interaction_rules or {}).get("allowed_recipients")
        if allowed:
            targets = [e for e in targets if e["target"] in allowed]

        if not targets:
            # conditions all failed -> dead end; surface output to user.
            self._emit(run.id, agent, output, recipient="user", status="done")
            return

        join_counts = _join_in_degree(graph)
        loop_edges = _loop_edges(graph)  # edges that close a cycle in the graph
        for e in targets:
            target = e["target"]
            if target == "user":
                self._emit(run.id, agent, output, recipient="user", status="done")
                self._finish_run(run.id, "completed")
                continue
            if e.get("join"):
                # fan-in barrier: wait for every join edge into this target.
                self._route_join(run, agent, output, target, join_counts[target])
                continue
            # A cycle-closing edge (e.g. Critic -> Writer) is a feedback-loop turn.
            # This is structural, not arrival-order based, so a plain diamond
            # (two non-join edges into one node) is NOT treated as a loop.
            if (agent.id, target) in loop_edges:
                if not self._take_loop(run.id):
                    # Loop budget exhausted -> stop looping and deliver the last
                    # actual artifact from the loop's target (e.g. the Writer's
                    # latest draft), not this agent's feedback message.
                    last = self._last_message_of(run.id, target)
                    if last and last.content.strip():
                        self._emit_raw(run.id, sender=last.sender, label=last.label,
                                       content=last.content, recipient="user", status="done")
                    else:
                        self._emit(run.id, agent, output, recipient="user", status="done")
                    self._finish_run(run.id, "completed")
                    continue
            self._emit(run.id, agent, output, recipient=target, status="pending")

    def _route_join(self, run: Run, agent: Agent, output: str, target: str, need: int):
        """Buffer fan-in until every source has arrived, then fire the target once."""
        # Record the contributing message so the UI shows it (already settled).
        self._emit(run.id, agent, output, recipient=target, status="done")
        buf = self._joins.setdefault((run.id, target), {})
        buf[agent.id] = output
        if len(buf) >= need:
            merged = "\n\n".join(
                f"### From {src}\n{txt}" for src, txt in buf.items()
            )
            self._emit_raw(run.id, sender="system", label="join",
                           content=merged, recipient=target, status="pending")
            self._joins.pop((run.id, target), None)

    # --- db helpers ---------------------------------------------------------
    def _load(self, run_id: str, agent_id: str):
        with Session(engine) as s:
            return s.get(Run, run_id), s.get(Agent, agent_id)

    def _run_status(self, run_id: str):
        with Session(engine) as s:
            r = s.get(Run, run_id)
            return r.status if r else None

    def _run_transcript(self, run_id: str, exclude_id: str):
        """The run's prior messages as chat turns, so the current agent has the
        full context (every agent's output is labelled)."""
        with Session(engine) as s:
            rows = s.exec(
                select(Message).where(Message.run_id == run_id)
                .order_by(Message.created_at)
            ).all()
        turns = []
        for m in rows:
            if m.id == exclude_id or not (m.content or "").strip():
                continue
            if m.recipient == "user":
                continue  # delivery copies, not part of the working context
            role = "user" if m.sender == "user" else "assistant"
            turns.append({"role": role, "content": f"[{m.label}] {m.content}"})
        return turns

    def _last_message_of(self, run_id: str, agent_id: str):
        """The most recent message produced by a given agent in this run."""
        with Session(engine) as s:
            return s.exec(
                select(Message).where(Message.run_id == run_id)
                .where(Message.sender == agent_id)
                .order_by(Message.created_at.desc())
            ).first()

    def _take_loop(self, run_id: str) -> bool:
        """Consume one loop turn. Returns False if the run is at its max_loops."""
        with Session(engine) as s:
            r = s.get(Run, run_id)
            if not r:
                return False
            if r.loops >= r.max_loops:
                return False
            r.loops += 1
            s.add(r)
            s.commit()
            return True

    def _graph(self, workflow_id: Optional[str]) -> dict:
        if not workflow_id:
            return {}
        with Session(engine) as s:
            wf = s.get(Workflow, workflow_id)
            return wf.graph if wf else {}

    def _emit(self, run_id, agent: Agent, content, recipient, status):
        self._emit_raw(run_id, sender=agent.id, label=agent.name,
                       content=content, recipient=recipient, status=status)

    def _emit_raw(self, run_id, sender, label, content, recipient, status):
        with Session(engine) as s:
            s.add(Message(run_id=run_id, sender=sender, label=label,
                          content=content, recipient=recipient, status=status))
            s.commit()

    def _settle(self, msg_id, status, error=None):
        with Session(engine) as s:
            m = s.get(Message, msg_id)
            if m:
                m.status = status
                m.error = error
                s.add(m)
                s.commit()

    def _bump_steps(self, run_id, cost: float = 0.0) -> float:
        """Increment step count + accumulate cost; return the run's total cost."""
        with Session(engine) as s:
            r = s.get(Run, run_id)
            if not r:
                return 0.0
            r.steps += 1
            r.cost += float(cost or 0.0)
            s.add(r)
            s.commit()
            return r.cost

    # --- memory -------------------------------------------------------------
    def _memory_on(self, agent: Agent) -> bool:
        return bool((agent.memory_config or {}).get("enabled"))

    def _load_memory(self, agent: Agent):
        """Return recent stored items as chat history, or None if disabled."""
        if not self._memory_on(agent):
            return None
        n = int((agent.memory_config or {}).get("max_items", 10))
        with Session(engine) as s:
            rows = s.exec(
                select(Memory).where(Memory.agent_id == agent.id)
                .order_by(Memory.created_at.desc()).limit(n)
            ).all()
        rows = list(reversed(rows))
        return [{"role": r.role, "content": r.content} for r in rows] or None

    def _save_memory(self, agent: Agent, user_input: str, output: str):
        if not self._memory_on(agent):
            return
        with Session(engine) as s:
            s.add(Memory(agent_id=agent.id, role="user", content=user_input))
            s.add(Memory(agent_id=agent.id, role="assistant", content=output))
            s.commit()

    def _finish_run(self, run_id, status):
        with Session(engine) as s:
            r = s.get(Run, run_id)
            if r and r.status == "running":
                r.status = status
                s.add(r)
                s.commit()


# --- condition / graph helpers ---------------------------------------------
def _apply_output_guardrails(agent: Agent, output: str) -> str:
    """Redact an agent's output if it contains any configured blocked word."""
    blocked = (agent.guardrails or {}).get("blocked_words") or []
    low = (output or "").lower()
    if any(w.lower() in low for w in blocked):
        return "[blocked by guardrail: output contained a disallowed term]"
    return output


def _passes(condition: Optional[dict], output: str) -> bool:
    """Evaluate an edge condition against an agent's output."""
    if not condition:
        return True
    if "contains" in condition:
        hit = condition["contains"].lower() in (output or "").lower()
        return not hit if condition.get("negate") else hit
    return True


def _loop_edges(graph: dict) -> set:
    """The feedback-loop edges: DFS back-edges (an edge to a node currently on
    the recursion stack, i.e. an ancestor). This picks only the *returning* edge
    of a cycle — e.g. Critic->Writer but not the forward Writer->Critic — and a
    plain diamond (A->B->D, A->C->D) yields none."""
    adj: Dict[str, list] = {}
    nodes = set()
    for e in graph.get("edges", []):
        adj.setdefault(e["source"], []).append(e["target"])
        nodes.add(e["source"])
        nodes.add(e["target"])

    back: set = set()
    visited: set = set()
    on_stack: set = set()

    def dfs(u: str):
        visited.add(u)
        on_stack.add(u)
        for v in adj.get(u, []):
            if v in on_stack:
                back.add((u, v))         # edge to an ancestor -> back-edge
            elif v not in visited:
                dfs(v)
        on_stack.discard(u)

    # Start from entry nodes, then any unvisited node (disconnected pieces).
    for root in list(graph.get("entry", [])) + list(nodes):
        if root not in visited:
            dfs(root)
    return back


def _join_in_degree(graph: dict) -> Dict[str, int]:
    """Count only edges marked ``join`` into each target (the barrier size)."""
    counts: Dict[str, int] = {}
    for e in graph.get("edges", []):
        if e.get("join"):
            counts[e["target"]] = counts.get(e["target"], 0) + 1
    return counts
