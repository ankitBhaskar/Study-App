"""Vercel Python entry point. Vercel's builder looks for a FastAPI/ASGI `app`
in this file specifically, so the real implementation lives in the
`study_app` package and is just re-exported here.

The explicit sys.path insert (rather than a plain `from study_app... import`)
makes this work regardless of how the file is invoked: `uvicorn
api.index:app` from the repo root (see README), a bare `python api/index.py`,
or however Vercel's own builder loads it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from study_app.factory import app  # noqa: E402

__all__ = ["app"]
