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
