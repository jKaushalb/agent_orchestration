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
from typing import Any, Callable, Dict, List, Optional

from sqlmodel import Session, select

from .db import engine
from .models import Agent, Message, Run, Workflow
from .runtime.runner import AgentRunConfig, run_agent


# The agent-execution function. Tests override this with a fake to avoid LLM calls.
RunFn = Callable[[AgentRunConfig, str], Any]


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
        try:
            result = await asyncio.to_thread(self._run_fn, cfg, m["content"])
            output = result.output if hasattr(result, "output") else str(result)
            cost = getattr(result, "cost", 0.0)
        except Exception as e:  # agent failed -> mark and stop this branch
            self._settle(m["id"], "failed", error=f"{type(e).__name__}: {e}")
            return

        self._bump_steps(run.id)
        self._route(run, agent, output, cost)
        self._settle(m["id"], "done")

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
        if not targets:
            # conditions all failed -> dead end; surface output to user.
            self._emit(run.id, agent, output, recipient="user", status="done")
            return

        join_counts = _join_in_degree(graph)
        for e in targets:
            target = e["target"]
            if target == "user":
                self._emit(run.id, agent, output, recipient="user", status="done")
                self._finish_run(run.id, "completed")
                continue
            if e.get("join"):
                # fan-in barrier: wait for every join edge into this target.
                self._route_join(run, agent, output, target, join_counts[target])
            else:
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

    def _bump_steps(self, run_id):
        with Session(engine) as s:
            r = s.get(Run, run_id)
            if r:
                r.steps += 1
                s.add(r)
                s.commit()

    def _finish_run(self, run_id, status):
        with Session(engine) as s:
            r = s.get(Run, run_id)
            if r and r.status == "running":
                r.status = status
                s.add(r)
                s.commit()


# --- condition / graph helpers ---------------------------------------------
def _passes(condition: Optional[dict], output: str) -> bool:
    """Evaluate an edge condition against an agent's output."""
    if not condition:
        return True
    if "contains" in condition:
        hit = condition["contains"].lower() in (output or "").lower()
        return not hit if condition.get("negate") else hit
    return True


def _join_in_degree(graph: dict) -> Dict[str, int]:
    """Count only edges marked ``join`` into each target (the barrier size)."""
    counts: Dict[str, int] = {}
    for e in graph.get("edges", []):
        if e.get("join"):
            counts[e["target"]] = counts.get(e["target"], 0) + 1
    return counts
