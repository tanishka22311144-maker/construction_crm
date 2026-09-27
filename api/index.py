"""Vercel entry point delegating directly to project.api.index."""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = ROOT_DIR / "project"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from project.api.index import app, handler

__all__ = ["app", "handler"]
