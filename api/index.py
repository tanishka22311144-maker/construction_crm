import os, sys
from pathlib import Path
# Add the sibling `project` directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent / "project"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from project.api.index import app as _app

# Vercel looks for a top‑level callable named `handler`. We also expose `app`
# for completeness and for any tooling that expects the FastAPI instance.
handler = _app
app = _app


# Vercel expects a callable named `handler`. This thin wrapper re‑exports the
# FastAPI application defined in `project/api/index.py`, which contains the
# Stage 2 webhook implementation (session‑variable RLS, tool execution, etc.).
# The legacy Stage 1 code that imported `run_agent` and `langgraph` has been
# removed, eliminating the `ModuleNotFoundError`.
