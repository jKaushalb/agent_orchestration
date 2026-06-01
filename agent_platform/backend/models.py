"""SQLModel tables for the platform.

Chunk 1 adds the Agent table — every column is one "configurable dimension"
(an impact metric from the brief): identity (name/role), behaviour
(system_prompt/model + client knobs), capabilities (tools/skills), connectivity
(channels), automation (schedule), state (memory), and safety
(interaction_rules/guardrails).

List/dict-valued config is stored in JSON columns so the model stays a single
flat row that the CRUD API and the React forms map onto directly.

Chunk 3 adds workflows, messages, runs, memory.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field


def _uuid() -> str:
    return uuid4().hex


class AgentBase(SQLModel):
    """Shared agent configuration — the full set of tunable dimensions."""

    # --- identity ---
    name: str
    role: str = ""

    # --- behaviour ---
    system_prompt: str = "You are a helpful agent."
    model: str = "gemini/gemini-2.5-flash"
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_output_tokens: int = Field(default=8126, gt=0)
    thinking: bool = False

    # --- capabilities ---
    tools: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    skills: List[str] = Field(default_factory=list, sa_column=Column(JSON))

    # --- connectivity ---
    channels: List[str] = Field(default_factory=list, sa_column=Column(JSON))

    # --- automation ---
    # cron-like schedule spec, e.g. {"cron": "0 8 * * *", "prompt": "..."}; null = none
    schedule: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # --- state ---
    # memory config, e.g. {"enabled": true, "max_items": 20}
    memory_config: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # --- safety / routing ---
    # who this agent may talk to, max turns, etc.
    interaction_rules: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    # caps + filters, e.g. {"max_cost_usd": 0.5, "blocked_words": [...]}
    guardrails: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # --- builder ---
    canvas_pos: Optional[Dict[str, float]] = Field(default=None, sa_column=Column(JSON))


class Agent(AgentBase, table=True):
    """Persisted agent row."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentCreate(AgentBase):
    """Request body for POST /agents."""


class AgentRead(AgentBase):
    """Response body — includes server-assigned fields."""

    id: str
    created_at: datetime


class AgentUpdate(SQLModel):
    """Request body for PUT /agents/{id} — all fields optional (partial update)."""

    name: Optional[str] = None
    role: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    thinking: Optional[bool] = None
    tools: Optional[List[str]] = None
    skills: Optional[List[str]] = None
    channels: Optional[List[str]] = None
    schedule: Optional[Dict[str, Any]] = None
    memory_config: Optional[Dict[str, Any]] = None
    interaction_rules: Optional[Dict[str, Any]] = None
    guardrails: Optional[Dict[str, Any]] = None
    canvas_pos: Optional[Dict[str, float]] = None


# ---------------------------------------------------------------------------
# Chunk 3: workflows, runs, and the message bus.
# ---------------------------------------------------------------------------
class Workflow(SQLModel, table=True):
    """A topology of agents. ``graph`` is the routing source of truth:

        {
          "entry": ["<agent_id>", ...],          # where a user request enters
          "nodes": [{"id": "<agent_id>", ...}],  # (optional) UI/canvas metadata
          "edges": [{"source": "<agent_id>",
                     "target": "<agent_id|user>",
                     "condition": {"contains": "approved", "negate": false}}]
        }

    Mesh, master/worker and feedback loops are all just different edge sets.
    """

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    graph: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Run(SQLModel, table=True):
    """One execution of a workflow (or a direct single-agent chat)."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    workflow_id: Optional[str] = None
    topic: str = ""
    status: str = "running"  # running | completed | failed
    steps: int = 0           # agent executions so far (loop guard)
    max_steps: int = 30      # hard cap so feedback loops always terminate
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Message(SQLModel, table=True):
    """A unit on the bus: async transport + persistence + UI feed, all in one.

    ``status`` drives the orchestrator:
      pending    -> waiting to be processed by ``recipient``
      processing -> claimed by the orchestrator
      done       -> processed (or a terminal/user-facing message)
      failed     -> the recipient agent errored
    """

    id: str = Field(default_factory=_uuid, primary_key=True)
    run_id: str = Field(index=True)
    sender: str = "user"                 # agent_id, "user", "system", or a channel
    recipient: Optional[str] = None      # agent_id to process; None/"user" = terminal
    label: str = "user"                  # display name for the UI (agent name / "user")
    content: str = ""
    content_type: str = "text"           # text | image
    attachments: Optional[List[Dict[str, Any]]] = Field(
        default=None, sa_column=Column(JSON)
    )
    status: str = "pending"
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
