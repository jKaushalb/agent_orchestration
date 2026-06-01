"""Seed the flagship Deep Research workflow on first run.

Creates a Lead, three Researchers, a Writer and a Critic, plus the workflow
graph wiring them (fan-out -> join -> write -> critique loop). Idempotent:
does nothing if any agents already exist.

Researchers use keyless tools (DuckDuckGo + Wikipedia + fetch_url) so the demo
works even without a Tavily key.
"""
from sqlmodel import Session, select

from .db import engine
from .models import Agent, Workflow

LEAD = (
    "You are the Lead researcher. Break the user's question into 3-4 concrete "
    "sub-topics to investigate and state them clearly so researchers can divide "
    "the work. Be brief."
)
RESEARCHER = (
    "You are a Researcher. Investigate the given topic using your tools "
    "(web_search2, wikipedia_extract, fetch_url). Return concise, factual bullet "
    "points with sources. Do not write prose."
)
WRITER = (
    "You are the Writer. The researchers' findings and any critic feedback are in "
    "the conversation above. Always output the COMPLETE article text itself (a "
    "full, well-structured article on the topic) — never commentary about it. If "
    "you received critic feedback, output the full REVISED article incorporating "
    "it. Save the final article with write_file when you have it."
)
CRITIC = (
    "You are the Critic. The full article to review is the most recent Writer "
    "message in the conversation above. Review it for accuracy, structure and "
    "clarity from a reader's perspective. If it needs work, give specific, "
    "actionable feedback and do NOT use the word approved. Only when it is "
    "genuinely good, reply starting with 'approved' followed by the complete "
    "final article text."
)


def seed_if_empty() -> None:
    with Session(engine) as s:
        if s.exec(select(Agent)).first():
            return

        def mk(name, role, prompt, tools):
            a = Agent(name=name, role=role, system_prompt=prompt, model="gemini/gemini-2.5-flash",
                      tools=tools, channels=["web", "telegram"], max_output_tokens=4000)
            s.add(a); s.commit(); s.refresh(a)
            return a.id

        research_tools = ["web_search2", "wikipedia_extract", "fetch_url"]
        lead = mk("Lead", "lead", LEAD, [])
        r1 = mk("Researcher 1", "researcher", RESEARCHER, research_tools)
        r2 = mk("Researcher 2", "researcher", RESEARCHER, research_tools)
        r3 = mk("Researcher 3", "researcher", RESEARCHER, research_tools)
        writer = mk("Writer", "writer", WRITER, ["write_file"])
        critic = mk("Critic", "critic", CRITIC, [])

        positions = {
            lead: (40, 200), r1: (260, 60), r2: (260, 200), r3: (260, 340),
            writer: (520, 200), critic: (760, 200),
        }
        graph = {
            "entry": [lead],
            "nodes": [
                {"id": aid, "position": {"x": x, "y": y}, "label": lbl}
                for aid, (x, y), lbl in [
                    (lead, positions[lead], "Lead"),
                    (r1, positions[r1], "Researcher 1"),
                    (r2, positions[r2], "Researcher 2"),
                    (r3, positions[r3], "Researcher 3"),
                    (writer, positions[writer], "Writer"),
                    (critic, positions[critic], "Critic"),
                ]
            ] + [{"id": "user", "position": {"x": 760, "y": 360}, "label": "USER ▸ deliver"}],
            "edges": [
                {"source": lead, "target": r1},
                {"source": lead, "target": r2},
                {"source": lead, "target": r3},
                {"source": r1, "target": writer, "join": True},
                {"source": r2, "target": writer, "join": True},
                {"source": r3, "target": writer, "join": True},
                {"source": writer, "target": critic},
                {"source": critic, "target": writer,
                 "condition": {"contains": "approved", "negate": True}},
                {"source": critic, "target": "user",
                 "condition": {"contains": "approved"}},
            ],
        }
        s.add(Workflow(name="Deep Research Assistant", graph=graph))
        s.commit()
