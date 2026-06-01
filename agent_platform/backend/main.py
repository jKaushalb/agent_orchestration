"""FastAPI application entrypoint.

The lifespan handler initializes the database now; later chunks start the
async orchestrator (Chunk 3), the scheduler (Chunk 7) and the Telegram
channel (Chunk 5) here too.
"""
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from .db import init_db
from .orchestrator import Orchestrator
from .routes import agents, messages

load_dotenv()

orchestrator = Orchestrator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    orchestrator.start()  # async message-bus worker
    # Chunk 5: start Telegram. Chunk 7: scheduler.
    try:
        yield
    finally:
        await orchestrator.stop()


app = FastAPI(title="Agent Platform", version="0.1.0", lifespan=lifespan)

app.include_router(agents.router)
app.include_router(messages.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "agent-platform"}
