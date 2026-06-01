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
        # per-chat selection: chat_id -> ("wf"|"agent", id), and loop budget
        self._chat_target: dict = {}
        self._chat_loops: dict = {}

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def start(self) -> None:
        if not self.enabled:
            return
        from telegram.ext import (ApplicationBuilder, CommandHandler,
                                   MessageHandler, filters)

        self.app = ApplicationBuilder().token(self.token).build()
        self.app.add_handler(CommandHandler(["start", "help"], self._cmd_help))
        self.app.add_handler(CommandHandler("workflows", self._cmd_workflows))
        self.app.add_handler(CommandHandler("use", self._cmd_use))
        self.app.add_handler(CommandHandler("turns", self._cmd_turns))
        self.app.add_handler(CommandHandler("current", self._cmd_current))
        # non-command text + photos go to the agent/workflow
        self.app.add_handler(
            MessageHandler((filters.TEXT & ~filters.COMMAND) | filters.PHOTO, self._on_message)
        )
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

        workflow_id, recipient = self._target_for(chat_id)
        if not workflow_id and not recipient:
            await msg.reply_text("No agents configured yet. Create one in the web UI.")
            return
        create_run(
            content=text, workflow_id=workflow_id, recipient=recipient,
            attachments=attachments, channel="telegram", chat_id=chat_id,
            max_loops=self._chat_loops.get(chat_id, 3),
        )

    # --- chat target + commands --------------------------------------------
    def _target_for(self, chat_id: str):
        """Per-chat selection if set, else the configured/default entry."""
        sel = self._chat_target.get(chat_id)
        if sel:
            kind, _id = sel
            return (_id, None) if kind == "wf" else (None, _id)
        return _entry()

    async def _cmd_help(self, update, context):
        await update.effective_message.reply_text(
            "Commands:\n"
            "/workflows — list workflows you can use\n"
            "/use <name|id> — pick a workflow (or an agent name) for this chat\n"
            "/turns <n> — max feedback-loop turns (default 3)\n"
            "/current — show this chat's selection\n\n"
            "Then just send a message to run it."
        )

    async def _cmd_workflows(self, update, context):
        with Session(engine) as s:
            wfs = s.exec(select(Workflow)).all()
        if not wfs:
            await update.effective_message.reply_text("No workflows yet — build one in the web UI.")
            return
        lines = "\n".join(f"• {w.name}" for w in wfs)
        await update.effective_message.reply_text(
            f"Workflows:\n{lines}\n\nPick one with /use <name>."
        )

    async def _cmd_use(self, update, context):
        chat_id = str(update.effective_chat.id)
        query = " ".join(context.args).strip()
        if not query:
            await update.effective_message.reply_text("Usage: /use <workflow name or id>")
            return
        with Session(engine) as s:
            wfs = s.exec(select(Workflow)).all()
            agents = s.exec(select(Agent)).all()
        q = query.lower()
        wf = next((w for w in wfs if w.id == query or w.name.lower() == q), None) \
            or next((w for w in wfs if q in w.name.lower()), None)
        if wf:
            self._chat_target[chat_id] = ("wf", wf.id)
            await update.effective_message.reply_text(f"This chat now uses workflow: {wf.name}")
            return
        ag = next((a for a in agents if a.id == query or a.name.lower() == q), None) \
            or next((a for a in agents if q in a.name.lower()), None)
        if ag:
            self._chat_target[chat_id] = ("agent", ag.id)
            await update.effective_message.reply_text(f"This chat now talks to agent: {ag.name}")
            return
        await update.effective_message.reply_text(f"No workflow or agent matching '{query}'.")

    async def _cmd_turns(self, update, context):
        chat_id = str(update.effective_chat.id)
        try:
            n = int(context.args[0])
            assert n >= 0
        except Exception:
            await update.effective_message.reply_text("Usage: /turns <non-negative integer>")
            return
        self._chat_loops[chat_id] = n
        await update.effective_message.reply_text(f"Max loop turns for this chat: {n}")

    async def _cmd_current(self, update, context):
        chat_id = str(update.effective_chat.id)
        wf_id, ag_id = self._target_for(chat_id)
        with Session(engine) as s:
            name = (s.get(Workflow, wf_id).name if wf_id else
                    (s.get(Agent, ag_id).name if ag_id else "none"))
        turns = self._chat_loops.get(chat_id, 3)
        await update.effective_message.reply_text(f"Using: {name} · max loop turns: {turns}")

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
