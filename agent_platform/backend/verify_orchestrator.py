"""Drive the orchestrator with a fake agent runner to prove the routing engine:
fan-out (Lead -> 3 Researchers), join (Researchers -> Writer), a feedback loop
(Writer <-> Critic until "approved"), conditions, and loop termination.

No LLM calls. Run from agent_platform/:  python -m backend.verify_orchestrator
"""
import asyncio
from dataclasses import dataclass

from sqlmodel import Session, select

from .db import engine, init_db
from .models import Agent, Message, Run, Workflow
from .orchestrator import Orchestrator
from .runtime.runner import RunResult


@dataclass
class _Fake:
    output: str
    cost: float = 0.0
    history: list = None


def make_fake_runner():
    """Return a run_fn(cfg, content) -> RunResult-like, deterministic per role."""
    state = {"writer": 0, "critic": 0}

    def run_fn(cfg, content):
        role = cfg.name
        if role == "Lead":
            return _Fake("decompose the question")
        if role.startswith("Researcher"):
            return _Fake(f"finding from {role}")
        if role == "Writer":
            state["writer"] += 1
            return _Fake(f"DRAFT v{state['writer']}")
        if role == "Critic":
            state["critic"] += 1
            # reject once, then approve -> exercises the feedback loop.
            return _Fake("needs work" if state["critic"] == 1 else "approved: looks great")
        return _Fake("ok")

    return run_fn


def seed():
    with Session(engine) as s:
        ids = {}
        for name in ["Lead", "Researcher1", "Researcher2", "Researcher3", "Writer", "Critic"]:
            a = Agent(name=name, role=name.lower(), system_prompt=f"You are {name}.")
            s.add(a)
            s.commit()
            s.refresh(a)
            ids[name] = a.id

        graph = {
            "entry": [ids["Lead"]],
            "edges": [
                {"source": ids["Lead"], "target": ids["Researcher1"]},
                {"source": ids["Lead"], "target": ids["Researcher2"]},
                {"source": ids["Lead"], "target": ids["Researcher3"]},
                {"source": ids["Researcher1"], "target": ids["Writer"], "join": True},
                {"source": ids["Researcher2"], "target": ids["Writer"], "join": True},
                {"source": ids["Researcher3"], "target": ids["Writer"], "join": True},
                {"source": ids["Writer"], "target": ids["Critic"]},
                # loop back while NOT approved
                {"source": ids["Critic"], "target": ids["Writer"],
                 "condition": {"contains": "approved", "negate": True}},
                # deliver when approved
                {"source": ids["Critic"], "target": "user",
                 "condition": {"contains": "approved"}},
            ],
        }
        wf = Workflow(name="Deep Research", graph=graph)
        s.add(wf)
        s.commit()
        s.refresh(wf)
        return wf.id, ids


async def main():
    init_db()
    wf_id, ids = seed()

    # ingest the user request: a pending message to the entry agent (Lead).
    with Session(engine) as s:
        run = Run(workflow_id=wf_id, topic="Impact of AI on jobs")
        s.add(run)
        s.commit()
        s.refresh(run)
        s.add(Message(run_id=run.id, sender="user", recipient=ids["Lead"],
                      label="user", content="Impact of AI on jobs", status="pending"))
        s.commit()
        run_id = run.id

    orch = Orchestrator(run_fn=make_fake_runner(), poll_interval=0.05)
    orch.start()

    # wait for the run to complete (or time out)
    for _ in range(200):
        await asyncio.sleep(0.1)
        with Session(engine) as s:
            r = s.get(Run, run_id)
            if r.status != "running":
                break
    await orch.stop()

    with Session(engine) as s:
        r = s.get(Run, run_id)
        msgs = s.exec(select(Message).where(Message.run_id == run_id)
                      .order_by(Message.created_at)).all()

    labels = [m.label for m in msgs]
    contents = [m.content for m in msgs]
    print("run status:", r.status, "| steps:", r.steps)
    print("message labels:", labels)

    # assertions
    assert r.status == "completed", "run did not complete"
    assert labels.count("Researcher1") + labels.count("Researcher2") + labels.count("Researcher3") == 3, "fan-out missing"
    assert any(c.startswith("DRAFT v2") for c in contents), "feedback loop did not re-run Writer"
    assert any("approved" in c for c in contents), "critic never approved"
    assert sum(1 for m in msgs if m.recipient == "user") >= 1, "no user-facing result"
    assert r.steps <= r.max_steps, "exceeded loop guard"
    print("\nOrchestrator checks passed: fan-out, join, feedback loop, termination.")


if __name__ == "__main__":
    asyncio.run(main())
