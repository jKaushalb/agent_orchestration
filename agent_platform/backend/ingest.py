"""Shared entry point for starting a run.

Used by both the HTTP route (POST /runs) and the Telegram channel, so a request
enters the message bus the same way regardless of where it came from.
"""
from typing import Any, Dict, List, Optional

from sqlmodel import Session

from .db import engine
from .models import Message, Run, Workflow


class IngestError(ValueError):
    pass


def resolve_entries(session: Session, workflow_id: Optional[str], recipient: Optional[str]) -> List[str]:
    if workflow_id:
        wf = session.get(Workflow, workflow_id)
        if wf is None:
            raise IngestError("Workflow not found")
        entries = list(wf.graph.get("entry", []))
        if not entries:
            raise IngestError("Workflow has no entry nodes")
        return entries
    if recipient:
        return [recipient]
    raise IngestError("Provide workflow_id or recipient")


def create_run(
    content: str,
    workflow_id: Optional[str] = None,
    recipient: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    channel: str = "web",
    chat_id: Optional[str] = None,
    max_loops: int = 3,
) -> str:
    """Create a Run and the entry message(s); returns the run id."""
    with Session(engine) as session:
        entries = resolve_entries(session, workflow_id, recipient)
        run = Run(
            workflow_id=workflow_id, topic=content, max_loops=max_loops,
            channel=channel, channel_chat_id=chat_id,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        for agent_id in entries:
            session.add(Message(
                run_id=run.id, sender="user", recipient=agent_id, label="user",
                content=content,
                content_type="image" if attachments else "text",
                attachments=attachments, status="pending",
            ))
        session.commit()
        return run.id
