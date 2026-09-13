from project.api.index import app as handler

# Vercel expects a callable named `handler`. This thin wrapper re‑exports the
# FastAPI application defined in `project/api/index.py`, which contains the
# Stage 2 webhook implementation (session‑variable RLS, tool execution, etc.).
# The legacy Stage 1 code that imported `run_agent` and `langgraph` has been
# removed, eliminating the `ModuleNotFoundError`.
