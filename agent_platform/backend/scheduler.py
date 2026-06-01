"""Agent schedules via APScheduler (in-process, no extra service).

An agent whose ``schedule`` is set runs automatically on a cadence, starting a
run with a configured prompt. Supported specs:

    {"cron": "0 8 * * *", "prompt": "Daily AI news digest"}
    {"every_seconds": 3600, "prompt": "..."}

Jobs are (re)loaded at startup and whenever agents change (the agents route
calls ``reload()``).
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, select

from .db import engine
from .ingest import create_run
from .models import Agent


def _run_scheduled_agent(agent_id: str, prompt: str):
    create_run(content=prompt, recipient=agent_id, channel="schedule")


class ScheduleManager:
    def __init__(self):
        self._sched = AsyncIOScheduler()

    def start(self):
        self._sched.start()
        self.reload()

    def shutdown(self):
        if self._sched.running:
            self._sched.shutdown(wait=False)

    def reload(self):
        """Rebuild jobs from the agents' current schedule config."""
        self._sched.remove_all_jobs()
        with Session(engine) as s:
            agents = s.exec(select(Agent)).all()
        for a in agents:
            spec = a.schedule or {}
            prompt = spec.get("prompt", "")
            trigger = self._trigger(spec)
            if trigger is not None and prompt:
                self._sched.add_job(
                    _run_scheduled_agent, trigger, args=[a.id, prompt],
                    id=f"agent:{a.id}", replace_existing=True,
                )

    @staticmethod
    def _trigger(spec: dict):
        if spec.get("cron"):
            try:
                return CronTrigger.from_crontab(spec["cron"])
            except Exception:
                return None
        if spec.get("every_seconds"):
            return IntervalTrigger(seconds=int(spec["every_seconds"]))
        return None
