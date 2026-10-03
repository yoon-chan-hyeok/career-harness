"""Container entrypoint: validated settings, explicit migrations, then one application process."""

import os
import sys

from alembic import command
from alembic.config import Config

from career.production import validate_runtime_settings


def main() -> None:
    try:
        validate_runtime_settings()
    except ValueError as error:
        # Validation errors contain setting names only, never credentials or a DB connection URL.
        raise SystemExit(str(error)) from None
    if os.getenv("RUN_MIGRATIONS", "0") == "1":
        command.upgrade(Config("alembic.ini"), "head")
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "career.api:app",
            "--host",
            "0.0.0.0",
            "--port",
            os.getenv("PORT", "8000"),
            "--no-access-log",
            "--proxy-headers",
            "--forwarded-allow-ips",
            os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        ],
    )


if __name__ == "__main__":
    main()
