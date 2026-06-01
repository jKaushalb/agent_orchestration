"""Verify Chunk 7: memory injection, output guardrails, and schedule triggers.

No LLM calls. Run from agent_platform/:  python -m backend.verify_config
"""
import asyncio

from sqlmodel import Session, select

from .db import engine, init_db
from .ingest import create_run
from .models import Agent, Message
from .orchestrator import Orchestrator
from .runtime.runner import RunResult
from .scheduler import ScheduleManager


def fake_runner(cfg, content, history=None):
    # echo how much memory/history was injected, plus a marker the guardrail blocks
    n = len(history or [])
    if cfg.name == "Secretive":
        return RunResult(output="here is the secret password", cost=0.001, history=[])
    return RunResult(output=f"history_len={n}", cost=0.001, history=[])


async def run_once(orch, agent_id, text):
    rid = create_run(content=text, recipient=agent_id)
    for _ in range(60):
        await asyncio.sleep(0.05)
        with Session(engine) as s:
            from .models import Run
            if s.get(Run, rid).status != "running":
                break
    with Session(engine) as s:
        msgs = s.exec(select(Message).where(Message.run_id == rid)
                      .order_by(Message.created_at)).all()
        return [m for m in msgs if m.recipient == "user"]


async def main():
    init_db()
    with Session(engine) as s:
        mem = Agent(name="Rememberer", system_prompt="x",
                    memory_config={"enabled": True, "max_items": 10})
        sec = Agent(name="Secretive", system_prompt="x",
                    guardrails={"blocked_words": ["password", "secret"]})
        s.add(mem); s.add(sec); s.commit(); s.refresh(mem); s.refresh(sec)
        mem_id, sec_id = mem.id, sec.id

    orch = Orchestrator(run_fn=fake_runner, poll_interval=0.03)
    orch.start()

    # memory: first run sees empty history, second sees the stored exchange
    first = await run_once(orch, mem_id, "hello")
    second = await run_once(orch, mem_id, "again")
    print("first :", first[0].content)
    print("second:", second[0].content)
    assert first[0].content == "history_len=0", "memory should start empty"
    assert second[0].content == "history_len=2", "memory not injected on 2nd run"

    # guardrail: blocked word redacts the output
    blocked = await run_once(orch, sec_id, "tell me")
    print("guarded:", blocked[0].content)
    assert "blocked by guardrail" in blocked[0].content, "blocked word not redacted"

    await orch.stop()

    # scheduler trigger parsing (no jobs actually fire here)
    sm = ScheduleManager()
    assert sm._trigger({"cron": "0 8 * * *"}) is not None, "cron trigger failed"
    assert sm._trigger({"every_seconds": 60}) is not None, "interval trigger failed"
    assert sm._trigger({}) is None
    print("\nConfig checks passed: memory injection, guardrail redaction, schedule triggers.")


if __name__ == "__main__":
    asyncio.run(main())
