"""Agent CRUD API.

Endpoints (all under /agents):
  POST   /agents        create
  GET    /agents        list
  GET    /agents/{id}   read one
  PUT    /agents/{id}   partial update
  DELETE /agents/{id}   delete
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Agent, AgentCreate, AgentRead, AgentUpdate

router = APIRouter(prefix="/agents", tags=["agents"])

# Optional hook invoked after any agent change (wired to scheduler.reload()).
_on_change = None


def set_on_change(fn):
    global _on_change
    _on_change = fn


def _changed():
    if _on_change:
        _on_change()


@router.post("", response_model=AgentRead, status_code=201)
def create_agent(payload: AgentCreate, session: Session = Depends(get_session)):
    agent = Agent.model_validate(payload)
    session.add(agent)
    session.commit()
    session.refresh(agent)
    _changed()
    return agent


@router.get("", response_model=List[AgentRead])
def list_agents(session: Session = Depends(get_session)):
    return session.exec(select(Agent)).all()


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(agent_id: str, session: Session = Depends(get_session)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/{agent_id}", response_model=AgentRead)
def update_agent(
    agent_id: str, payload: AgentUpdate, session: Session = Depends(get_session)
):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(agent, key, value)
    session.add(agent)
    session.commit()
    session.refresh(agent)
    _changed()
    return agent


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: str, session: Session = Depends(get_session)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    session.delete(agent)
    session.commit()
    _changed()
