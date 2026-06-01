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
from ..ingest import IngestError, create_run
from ..models import Message, Run

router = APIRouter(tags=["runs"])


class StartRun(BaseModel):
    content: str
    workflow_id: Optional[str] = None
    recipient: Optional[str] = None  # for a direct single-agent chat
    attachments: Optional[List[Dict[str, Any]]] = None
    max_loops: int = 3  # max feedback-loop turns ("max turns in a loop")


@router.post("/runs", status_code=201)
def start_run(payload: StartRun):
    try:
        run_id = create_run(
            content=payload.content,
            workflow_id=payload.workflow_id,
            recipient=payload.recipient,
            attachments=payload.attachments,
            max_loops=payload.max_loops,
        )
    except IngestError as e:
        raise HTTPException(400, str(e))
    return {"run_id": run_id}


@router.get("/runs")
def list_runs(session: Session = Depends(get_session)):
    """Past + active sessions, newest first (for the history list)."""
    return session.exec(select(Run).order_by(Run.created_at.desc())).all()


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: str, session: Session = Depends(get_session)):
    """Stop a running workflow: mark it stopped and settle its open messages so
    the orchestrator does no further work for it."""
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    if run.status == "running":
        run.status = "stopped"
        session.add(run)
        open_msgs = session.exec(
            select(Message).where(Message.run_id == run_id)
            .where(Message.status.in_(["pending", "processing"]))
        ).all()
        for m in open_msgs:
            m.status = "done"
            session.add(m)
        session.commit()
        session.refresh(run)
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
                # Read run status BEFORE messages: the orchestrator commits a
                # message and only then marks the run finished, so if we observe
                # "finished" we are guaranteed a subsequent message read includes
                # the final delivered artifact (no lost-last-message race).
                run = s.get(Run, run_id)
                rows = s.exec(
                    select(Message).where(Message.run_id == run_id)
                    .order_by(Message.created_at)
                ).all()
            new = [m for m in rows if m.id not in seen]
            for m in new:
                seen.add(m.id)
                yield f"data: {json.dumps(_serialize(m))}\n\n"
            idle = 0 if new else idle + 1
            if run and run.status != "running" and not new:
                yield f"event: done\ndata: {json.dumps({'status': run.status})}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
