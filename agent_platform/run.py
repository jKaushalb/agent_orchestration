"""Single-command launcher.

    python run.py

Builds the frontend if needed (requires Node), then starts the FastAPI backend
with the orchestrator, scheduler and (if configured) Telegram channel. The
backend serves the built UI at http://localhost:8000, so this one command runs
the whole platform locally.

Use `--no-frontend` to skip the build and run the API only (use the Vite dev
server separately for frontend hot-reload).
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"


def ensure_frontend() -> None:
    if DIST.is_dir():
        return
    npm = shutil.which("npm")
    if not npm:
        print("[run] npm not found — skipping UI build. API will run without the UI.")
        print("[run] Install Node, or run the frontend separately with `npm run dev`.")
        return
    print("[run] Building frontend (first run)…")
    if not (FRONTEND / "node_modules").is_dir():
        subprocess.run([npm, "install"], cwd=FRONTEND, check=True, shell=False)
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True, shell=False)


def main() -> None:
    if "--no-frontend" not in sys.argv:
        ensure_frontend()
    import uvicorn

    print("[run] Starting Agent Platform on http://localhost:8000")
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
