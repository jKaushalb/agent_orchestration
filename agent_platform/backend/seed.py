"""Seed workflows + agents, and a full reset.

Two flagship workflows are created with fresh prompts:

- **Deep Research Assistant** — Lead fans a question out to 3 Researchers
  (parallel), their findings join into a Writer, a Critic loops until approved.
- **Article Generation** — a focused pipeline: Researcher -> Writer -> Editor,
  with the Editor looping back to the Writer until the article is approved.

``seed_if_empty()`` seeds both on first run (no agents yet). ``reset_and_seed()``
purges all data (agents, workflows, runs, messages, memory) and recreates them.
"""
from sqlmodel import Session, select

from .db import engine
from .models import Agent, Memory, Message, Run, Workflow

# --- Deep Research prompts ---------------------------------------------------
DR_LEAD = (
    "You are the Lead researcher and coordinator. Read the user's question and "
    "break it into 3-4 specific, non-overlapping sub-topics worth investigating. "
    "State each sub-topic clearly and concisely so researchers can divide the "
    "work. Do not answer the question yourself."
)
DR_RESEARCHER = (
    "You are a Researcher. Investigate the topic using your tools: search with "
    "web_search2, look up background with wikipedia_extract, and read the most "
    "relevant pages with fetch_url. Return concise, factual bullet points, each "
    "with its source URL. Do not write prose or an article — just findings."
)
DR_WRITER = (
    "You are the Writer. The researchers' findings (and any critic feedback) are "
    "in the conversation above. Synthesize them into one clear, well-structured, "
    "engaging article on the user's topic. Output the COMPLETE article text only "
    "— never commentary or notes about it. If you received feedback, output the "
    "full REVISED article. Then save it with write_file."
)
DR_CRITIC = (
    "You are the Critic. The article to review is the most recent Writer message "
    "above. Judge accuracy, structure, flow and clarity for a general reader. If "
    "it can be improved, give specific, numbered, actionable feedback and do NOT "
    "use the word 'approved'. When the article is genuinely strong, reply with "
    "the word 'approved' on the first line, followed by the final article text."
)

# --- Article Generation prompts ---------------------------------------------
AG_RESEARCHER = (
    "You are the Researcher for an article. Gather the key facts, context and a "
    "few good examples on the requested topic using web_search2, wikipedia_extract "
    "and fetch_url. Return concise, sourced bullet-point notes the writer can use. "
    "Do not write the article yourself."
)
AG_WRITER = (
    "You are the Writer. Using the research notes and any editor feedback in the "
    "conversation above, write a complete, engaging article on the requested topic "
    "with a title, a short intro, clear sections, and a conclusion. Output ONLY "
    "the full article text (never commentary). If you received feedback, output "
    "the full revised article. Then save it with write_file."
)
AG_EDITOR = (
    "You are the Editor. Review the most recent Writer article above for clarity, "
    "structure, tone and correctness. If it needs work, give specific, actionable "
    "edits and do NOT use the word 'approved'. When it is polished and ready, "
    "reply with 'approved' on the first line, followed by the final article text."
)

RESEARCH_TOOLS = ["web_search2", "wikipedia_extract", "fetch_url"]


def _mk(s: Session, name, role, prompt, tools) -> str:
    a = Agent(name=name, role=role, system_prompt=prompt,
              model="gemini/gemini-2.5-flash", tools=tools,
              channels=["web", "telegram"], max_output_tokens=4000)
    s.add(a)
    s.commit()
    s.refresh(a)
    return a.id


def _node(aid, x, y, label):
    return {"id": aid, "position": {"x": x, "y": y}, "label": label}


def seed_deep_research(s: Session) -> None:
    lead = _mk(s, "Lead", "lead", DR_LEAD, [])
    r1 = _mk(s, "Researcher 1", "researcher", DR_RESEARCHER, RESEARCH_TOOLS)
    r2 = _mk(s, "Researcher 2", "researcher", DR_RESEARCHER, RESEARCH_TOOLS)
    r3 = _mk(s, "Researcher 3", "researcher", DR_RESEARCHER, RESEARCH_TOOLS)
    writer = _mk(s, "Writer", "writer", DR_WRITER, ["write_file"])
    critic = _mk(s, "Critic", "critic", DR_CRITIC, [])
    graph = {
        "entry": [lead],
        "nodes": [
            _node(lead, 40, 200, "Lead"),
            _node(r1, 260, 60, "Researcher 1"),
            _node(r2, 260, 200, "Researcher 2"),
            _node(r3, 260, 340, "Researcher 3"),
            _node(writer, 520, 200, "Writer"),
            _node(critic, 760, 200, "Critic"),
            _node("user", 760, 360, "USER ▸ deliver"),
        ],
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
            {"source": critic, "target": "user", "condition": {"contains": "approved"}},
        ],
    }
    s.add(Workflow(name="Deep Research Assistant", graph=graph))
    s.commit()


def seed_article_generation(s: Session) -> None:
    researcher = _mk(s, "Article Researcher", "researcher", AG_RESEARCHER, RESEARCH_TOOLS)
    writer = _mk(s, "Article Writer", "writer", AG_WRITER, ["write_file"])
    editor = _mk(s, "Editor", "editor", AG_EDITOR, [])
    graph = {
        "entry": [researcher],
        "nodes": [
            _node(researcher, 60, 160, "Article Researcher"),
            _node(writer, 320, 160, "Article Writer"),
            _node(editor, 580, 160, "Editor"),
            _node("user", 580, 320, "USER ▸ deliver"),
        ],
        "edges": [
            {"source": researcher, "target": writer},
            {"source": writer, "target": editor},
            {"source": editor, "target": writer,
             "condition": {"contains": "approved", "negate": True}},
            {"source": editor, "target": "user", "condition": {"contains": "approved"}},
        ],
    }
    s.add(Workflow(name="Article Generation", graph=graph))
    s.commit()


def seed_if_empty() -> None:
    with Session(engine) as s:
        if s.exec(select(Agent)).first():
            return
        seed_deep_research(s)
        seed_article_generation(s)


def purge_all() -> None:
    """Delete all runtime + config data."""
    with Session(engine) as s:
        for model in (Message, Run, Memory, Workflow, Agent):
            for row in s.exec(select(model)).all():
                s.delete(row)
        s.commit()


def reset_and_seed() -> None:
    """Purge everything, then recreate both workflows with fresh agents/prompts."""
    purge_all()
    with Session(engine) as s:
        seed_deep_research(s)
        seed_article_generation(s)
