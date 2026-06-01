"""SQLite engine + session helpers (SQLModel).

Single-file local database -> satisfies the "fully local, single command"
requirement with zero setup. The DB file lives under backend/data/.
"""
import os
from pathlib import Path
from sqlalchemy import inspect, text
from sqlmodel import SQLModel, Session, create_engine

# DB path is overridable via PLATFORM_DB (lets tests / extra instances use their
# own file instead of contending for the default one).
if os.environ.get("PLATFORM_DB"):
    DB_PATH = Path(os.environ["PLATFORM_DB"])
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
else:
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
    """Create tables for all imported SQLModel models, then add any columns that
    were introduced after an existing DB was created (lightweight migration)."""
    # Import models so they register on SQLModel.metadata before create_all.
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """SQLite can't add columns via create_all; ALTER in any model column that an
    older DB is missing, so the app keeps working across schema additions."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.tables.values():
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                coltype = col.type.compile(engine.dialect)
                default = ""
                arg = getattr(col.default, "arg", None)
                if arg is not None and not callable(arg):
                    if isinstance(arg, bool):
                        default = f" DEFAULT {1 if arg else 0}"
                    elif isinstance(arg, (int, float)):
                        default = f" DEFAULT {arg}"
                    elif isinstance(arg, str):
                        default = f" DEFAULT '{arg}'"
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}{default}')
                )


def get_session() -> Session:
    """FastAPI dependency: yields a session per request."""
    with Session(engine) as session:
        yield session
