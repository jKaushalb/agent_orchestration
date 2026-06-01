"""Workflow CRUD API.

A workflow's ``graph`` is the routing source of truth the orchestrator reads
(entry nodes + edges with conditions/join). The React Flow builder reads and
writes it through these endpoints.

  POST   /workflows        create
  GET    /workflows        list
  GET    /workflows/{id}   read one
  PUT    /workflows/{id}   update (name and/or graph)
  DELETE /workflows/{id}   delete
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import Workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowIn(BaseModel):
    name: str
    graph: Dict[str, Any] = {}


class WorkflowPatch(BaseModel):
    name: Optional[str] = None
    graph: Optional[Dict[str, Any]] = None


@router.post("", status_code=201, response_model=Workflow)
def create_workflow(payload: WorkflowIn, session: Session = Depends(get_session)):
    wf = Workflow(name=payload.name, graph=payload.graph)
    session.add(wf)
    session.commit()
    session.refresh(wf)
    return wf


@router.get("", response_model=List[Workflow])
def list_workflows(session: Session = Depends(get_session)):
    return session.exec(select(Workflow)).all()


@router.get("/{workflow_id}", response_model=Workflow)
def get_workflow(workflow_id: str, session: Session = Depends(get_session)):
    wf = session.get(Workflow, workflow_id)
    if wf is None:
        raise HTTPException(404, "Workflow not found")
    return wf


@router.put("/{workflow_id}", response_model=Workflow)
def update_workflow(
    workflow_id: str, payload: WorkflowPatch, session: Session = Depends(get_session)
):
    wf = session.get(Workflow, workflow_id)
    if wf is None:
        raise HTTPException(404, "Workflow not found")
    if payload.name is not None:
        wf.name = payload.name
    if payload.graph is not None:
        wf.graph = payload.graph
    session.add(wf)
    session.commit()
    session.refresh(wf)
    return wf


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: str, session: Session = Depends(get_session)):
    wf = session.get(Workflow, workflow_id)
    if wf is None:
        raise HTTPException(404, "Workflow not found")
    session.delete(wf)
    session.commit()
