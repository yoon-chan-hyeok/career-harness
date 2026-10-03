"""Dedicated Vercel FastAPI entrypoint; local development uses career.api directly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from career.serverless import prepare_serverless_environment  # noqa: E402

prepare_serverless_environment()

from career.api import app as app  # noqa: E402
