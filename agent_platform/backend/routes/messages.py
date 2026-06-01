"""Runs & messages API — ingest requests and read the persisted conversation.

  POST /runs              start a run (workflow or direct single-agent chat)
  GET  /runs/{id}         run status
  GET  /messages?run_id   full message history for a run (the UI feed)
  GET  /messages/stream   server-sent events: live messages for a run
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import engine, get_session
from ..models import Message, Run, Workflow

router = APIRouter(tags=["runs"])


class StartRun(BaseModel):
    content: str
    workflow_id: Optional[str] = None
    recipient: Optional[str] = None  # for a direct single-agent chat
    attachments: Optional[List[Dict[str, Any]]] = None
    max_steps: int = 30


@router.post("/runs", status_code=201)
def start_run(payload: StartRun, session: Session = Depends(get_session)):
    # Resolve entry recipients: workflow entry nodes, or a direct recipient.
    entries: List[str] = []
    if payload.workflow_id:
        wf = session.get(Workflow, payload.workflow_id)
        if wf is None:
            raise HTTPException(404, "Workflow not found")
        entries = list(wf.graph.get("entry", []))
        if not entries:
            raise HTTPException(400, "Workflow has no entry nodes")
    elif payload.recipient:
        entries = [payload.recipient]
    else:
        raise HTTPException(400, "Provide workflow_id or recipient")

    run = Run(workflow_id=payload.workflow_id, topic=payload.content,
              max_steps=payload.max_steps)
    session.add(run)
    session.commit()
    session.refresh(run)

    for agent_id in entries:
        session.add(Message(
            run_id=run.id, sender="user", recipient=agent_id, label="user",
            content=payload.content,
            content_type="image" if payload.attachments else "text",
            attachments=payload.attachments, status="pending",
        ))
    session.commit()
    return {"run_id": run.id}


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@router.get("/messages")
def list_messages(run_id: str = Query(...), session: Session = Depends(get_session)):
    rows = session.exec(
        select(Message).where(Message.run_id == run_id).order_by(Message.created_at)
    ).all()
    return rows


def _serialize(m: Message) -> dict:
    return {
        "id": m.id, "run_id": m.run_id, "sender": m.sender, "label": m.label,
        "recipient": m.recipient, "content": m.content, "status": m.status,
        "created_at": m.created_at.isoformat(),
    }


@router.get("/messages/stream")
async def stream_messages(run_id: str = Query(...)):
    """SSE stream: emits each new message for a run as it appears."""

    async def event_gen():
        seen: set = set()
        idle = 0
        while idle < 600:  # ~5 min cap on an idle stream
            with Session(engine) as s:
                rows = s.exec(
                    select(Message).where(Message.run_id == run_id)
                    .order_by(Message.created_at)
                ).all()
                new = [m for m in rows if m.id not in seen]
                run = s.get(Run, run_id)
            for m in new:
                seen.add(m.id)
                yield f"data: {json.dumps(_serialize(m))}\n\n"
            if new:
                idle = 0
            else:
                idle += 1
            if run and run.status != "running" and not new:
                yield f"event: done\ndata: {json.dumps({'status': run.status})}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
