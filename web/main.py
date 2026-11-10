"""Uppcoder starts this as uvicorn main:app from the web directory.

LUNA ZHOU, 2026-11-10.
The shared planner lives at the repository root so the desktop pet and this
API do not keep two copies. Uppcoder's working directory is web/, so the
root has to be importable before the app loads.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.api import create_app

app = create_app()
