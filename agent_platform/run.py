"""Single-command launcher for the platform.

Starts the FastAPI backend with uvicorn. Once the frontend is built (Chunk 4),
this also serves / launches the React dev server. Run from the agent_platform/
directory:

    python run.py
"""
import uvicorn

if __name__ == "__main__":
    # reload=False keeps it to a single command with no extra processes.
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
