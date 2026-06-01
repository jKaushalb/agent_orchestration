"""Telegram channel (long polling).

Long polling means no public URL, no webhook, no business approval — it runs
fully local. Inbound Telegram messages enter the same message bus as the web UI
(via ingest.create_run); terminal agent output for Telegram-originated runs is
pushed back to the chat by a small async poller.

Entry point (which agent/workflow a Telegram message hits) is chosen by:
  TELEGRAM_ENTRY_WORKFLOW  -> a workflow id, else
  TELEGRAM_ENTRY_AGENT     -> an agent id, else
  the first workflow, else the first agent.

Enabled only when TELEGRAM_BOT_TOKEN is set; otherwise start() is a no-op.
"""
import asyncio
import base64
import os
from typing import Optional

from sqlmodel import Session, select

from ..db import engine
from ..ingest import create_run
from ..models import Agent, Message, Run, Workflow


def _entry():
    """Return (workflow_id, recipient) for an inbound Telegram message."""
    wf = os.environ.get("TELEGRAM_ENTRY_WORKFLOW")
    if wf:
        return wf, None
    ag = os.environ.get("TELEGRAM_ENTRY_AGENT")
    if ag:
        return None, ag
    with Session(engine) as s:
        w = s.exec(select(Workflow)).first()
        if w:
            return w.id, None
        a = s.exec(select(Agent)).first()
        if a:
            return None, a.id
    return None, None


class TelegramChannel:
    def __init__(self):
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.app = None
        self._deliver_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def start(self) -> None:
        if not self.enabled:
            return
        from telegram.ext import (ApplicationBuilder, MessageHandler, filters)

        self.app = ApplicationBuilder().token(self.token).build()
        self.app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, self._on_message))
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        self._stop.clear()
        self._deliver_task = asyncio.create_task(self._deliver_loop())

    async def stop(self) -> None:
        if not self.app:
            return
        self._stop.set()
        if self._deliver_task:
            await self._deliver_task
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    # --- inbound ------------------------------------------------------------
    async def _on_message(self, update, context):
        msg = update.effective_message
        chat_id = str(update.effective_chat.id)
        text = msg.text or msg.caption or ""

        attachments = None
        if msg.photo:
            # largest size is last; download and base64-encode for the runtime.
            file = await context.bot.get_file(msg.photo[-1].file_id)
            buf = await file.download_as_bytearray()
            attachments = [{"type": "image", "data": base64.b64encode(bytes(buf)).decode()}]
            text = text or "Analyze this image."

        workflow_id, recipient = _entry()
        if not workflow_id and not recipient:
            await msg.reply_text("No agents configured yet. Create one in the web UI.")
            return
        create_run(
            content=text, workflow_id=workflow_id, recipient=recipient,
            attachments=attachments, channel="telegram", chat_id=chat_id,
        )

    # --- outbound -----------------------------------------------------------
    async def _deliver_loop(self):
        """Push terminal (user-facing) messages of Telegram runs back to chats."""
        while not self._stop.is_set():
            for chat_id, text, mid in self._undelivered():
                try:
                    await self.app.bot.send_message(chat_id=chat_id, text=text[:4000])
                    self._mark_delivered(mid)
                except Exception:
                    self._mark_delivered(mid)  # avoid a poison message looping forever
            await asyncio.sleep(1.0)

    def _undelivered(self):
        out = []
        with Session(engine) as s:
            tg_runs = {r.id: r.channel_chat_id
                       for r in s.exec(select(Run).where(Run.channel == "telegram")).all()}
            if not tg_runs:
                return out
            rows = s.exec(
                select(Message).where(Message.recipient == "user")
                .where(Message.delivered == False)  # noqa: E712
            ).all()
            for m in rows:
                if m.run_id in tg_runs and tg_runs[m.run_id]:
                    out.append((tg_runs[m.run_id], m.content, m.id))
        return out

    def _mark_delivered(self, message_id):
        with Session(engine) as s:
            m = s.get(Message, message_id)
            if m:
                m.delivered = True
                s.add(m)
                s.commit()
