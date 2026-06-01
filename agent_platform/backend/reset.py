"""Purge all data and re-seed the two workflows with fresh agents/prompts.

Run from agent_platform/ with the server STOPPED (it holds the DB):

    python -m backend.reset
"""
from sqlmodel import Session, select

from .db import engine, init_db
from .models import Agent, Workflow
from .seed import reset_and_seed


def main() -> None:
    init_db()
    reset_and_seed()
    with Session(engine) as s:
        agents = s.exec(select(Agent)).all()
        workflows = s.exec(select(Workflow)).all()
    print(f"Purged and re-seeded. {len(agents)} agents, {len(workflows)} workflows:")
    for w in workflows:
        names = [n["label"] for n in w.graph.get("nodes", []) if n["id"] != "user"]
        print(f"  • {w.name}: {', '.join(names)}")


if __name__ == "__main__":
    main()
