"""FastAPI application entrypoint.

The lifespan handler initializes the database now; later chunks start the
async orchestrator (Chunk 3), the scheduler (Chunk 7) and the Telegram
channel (Chunk 5) here too.
"""
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .channels.telegram import TelegramChannel
from .db import init_db
from .orchestrator import Orchestrator
from .routes import agents, messages, workflows
from .runtime.tools import AVAILABLE_TOOLS
from .scheduler import ScheduleManager

load_dotenv()

orchestrator = Orchestrator()
telegram = TelegramChannel()
scheduler = ScheduleManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    orchestrator.start()  # async message-bus worker
    await telegram.start()  # no-op unless TELEGRAM_BOT_TOKEN is set
    scheduler.start()  # agent schedules
    # agent CRUD reloads the scheduler when schedules change
    agents.set_on_change(scheduler.reload)
    try:
        yield
    finally:
        scheduler.shutdown()
        await telegram.stop()
        await orchestrator.stop()


app = FastAPI(title="Agent Platform", version="0.1.0", lifespan=lifespan)

# Allow the React dev server (and any local origin) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router)
app.include_router(messages.router)
app.include_router(workflows.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "agent-platform"}


@app.get("/tools")
def list_tools():
    """Tool keys an agent can be configured with (used by the agent form)."""
    return AVAILABLE_TOOLS


# Preset models offered in the agent form. litellm resolves credentials from the
# model-name prefix; users can also type any custom litellm model id.
PRESET_MODELS = [
    {"id": "gemini/gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
    {"id": "gemini/gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
    {"id": "gemini/gemini-3.5-flash", "label": "Gemini 3.5 Flash"},
    {"id": "anthropic/claude-sonnet-4-5", "label": "Claude Sonnet 4.5"},
    {"id": "anthropic/claude-opus-4-1", "label": "Claude Opus 4.1"},
    {"id": "openai/gpt-4o", "label": "OpenAI GPT-4o"},
    {"id": "openai/gpt-4o-mini", "label": "OpenAI GPT-4o mini"},
]


@app.get("/models")
def list_models():
    """Preset model options for the agent form (custom ids are still allowed)."""
    return PRESET_MODELS
