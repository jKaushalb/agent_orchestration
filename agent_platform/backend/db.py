"""SQLite engine + session helpers (SQLModel).

Single-file local database -> satisfies the "fully local, single command"
requirement with zero setup. The DB file lives under backend/data/.
"""
from pathlib import Path
from sqlmodel import SQLModel, Session, create_engine

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "platform.db"

# check_same_thread=False so the async orchestrator and request handlers can
# share the engine across threads.
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Create tables for all imported SQLModel models."""
    # Import models so they register on SQLModel.metadata before create_all.
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    """FastAPI dependency: yields a session per request."""
    with Session(engine) as session:
        yield session
