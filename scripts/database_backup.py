"""Private, checked backups and restoration into an explicitly confirmed empty target."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from career import models  # noqa: E402,F401
from career.db import Base, database_url, make_engine  # noqa: E402


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1_048_576), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def pg_environment(url: str) -> dict[str, str]:
    parsed = database_url(url)
    environment = dict(os.environ)
    environment.update(
        {
            "PGHOST": parsed.host or "localhost",
            "PGPORT": str(parsed.port or 5432),
            "PGDATABASE": parsed.database or "postgres",
            "PGUSER": parsed.username or "postgres",
            "PGPASSWORD": parsed.password or "",
            "PGCONNECT_TIMEOUT": "10",
        }
    )
    for query, env in [("sslmode", "PGSSLMODE"), ("sslrootcert", "PGSSLROOTCERT")]:
        value = parsed.query.get(query)
        if isinstance(value, str):
            environment[env] = value
    return environment


def career_tables() -> list[str]:
    return list(Base.metadata.tables) + ["evidence_embeddings", "alembic_version"]


def backup(url: str, output: Path) -> dict[str, Any]:
    parsed = database_url(url)
    if output.exists() or Path(str(output) + ".json").exists():
        raise ValueError("Backup destination already exists; choose a new path")
    output.parent.mkdir(parents=True, exist_ok=True)
    if parsed.get_backend_name() == "sqlite":
        if parsed.database in {None, "", ":memory:"}:
            raise ValueError("A file-based SQLite database is required")
        source = Path(parsed.database).resolve()
        if not source.is_file() or source == output.resolve():
            raise ValueError("Valid, distinct source and destination paths are required")
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as source_db:
            with sqlite3.connect(output) as destination:
                source_db.backup(destination)
                result = destination.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise ValueError("SQLite backup integrity check failed")
        kind = "sqlite"
    elif parsed.get_backend_name() == "postgresql":
        command = shutil.which("pg_dump")
        if not command:
            raise ValueError("Install PostgreSQL client tools matching the target server major version")
        arguments = [command, "--format=custom", "--no-owner", "--no-acl", "--file", str(output)]
        arguments.extend("--table=public." + name for name in career_tables())
        subprocess.run(arguments, env=pg_environment(url), check=True, capture_output=True, timeout=600)
        kind = "postgresql-custom"
    else:
        raise ValueError("Unsupported database driver")
    manifest = {
        "format": kind,
        "sha256": digest(output),
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "career_tables_only" if kind == "postgresql-custom" else "local_database",
        "contains_private_data": True,
    }
    Path(str(output) + ".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def validate_backup(path: Path) -> dict[str, Any]:
    manifest = json.loads(Path(str(path) + ".json").read_text(encoding="utf-8"))
    if not path.is_file() or manifest.get("sha256") != digest(path):
        raise ValueError("Backup checksum does not match its manifest")
    return manifest


def verify_empty_target(url: str) -> None:
    from sqlalchemy import inspect, text

    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            tables = inspect(connection).get_table_names()
            allowed = set(career_tables())
            if any(name not in allowed for name in tables):
                raise ValueError("Target contains unrelated tables; use a dedicated empty target")
            for name in tables:
                if name == "alembic_version":
                    continue
                # The name is from the fixed ORM/migration allowlist, never from a supplied query.
                if connection.execute(text('SELECT count(*) FROM "' + name + '"')).scalar():
                    raise ValueError("Target contains application data; restore to a different empty target")
    finally:
        engine.dispose()


def restore(url: str, path: Path, confirmed_empty: bool) -> None:
    if not confirmed_empty:
        raise ValueError("Explicit --confirm-empty-target is required")
    manifest = validate_backup(path)
    verify_empty_target(url)
    parsed = database_url(url)
    if manifest.get("format") == "sqlite" and parsed.get_backend_name() == "sqlite":
        target = Path(parsed.database or "").resolve()
        if target == path.resolve() or parsed.database in {None, "", ":memory:"}:
            raise ValueError("A distinct file-based restore target is required")
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(target) as destination:
                source.backup(destination)
    elif manifest.get("format") == "postgresql-custom" and parsed.get_backend_name() == "postgresql":
        command = shutil.which("pg_restore")
        if not command:
            raise ValueError("Install matching PostgreSQL client tools")
        subprocess.run(
            [
                command,
                "--dbname",
                parsed.database or "postgres",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "--single-transaction",
                str(path),
            ],
            env=pg_environment(url),
            check=True,
            capture_output=True,
            timeout=600,
        )
    else:
        raise ValueError("Backup format does not match the target database")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    create = actions.add_parser("backup")
    create.add_argument(
        "--output",
        type=Path,
        default=Path("work/backups") / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".backup"),
    )
    recover = actions.add_parser("restore")
    recover.add_argument("backup", type=Path)
    recover.add_argument("--execute", action="store_true")
    recover.add_argument("--confirm-empty-target", action="store_true")
    args = parser.parse_args()
    url = os.getenv("DATABASE_URL", "sqlite:///./career.db")
    try:
        if args.action == "backup":
            backup(url, args.output)
            print("Private backup and checksum manifest saved. Keep both outside version control.")
        elif not args.execute:
            validate_backup(args.backup)
            print("Checksum verified. Restore preview only; requires --execute --confirm-empty-target.")
        else:
            restore(url, args.backup, args.confirm_empty_target)
            print(
                "Restored into verified empty target. Reapply Data API protection and verify /ready before serving traffic."
            )
    except Exception as error:
        # pg_dump/driver diagnostics could reveal hosts/usernames; never emit their raw stderr or URLs.
        raise SystemExit("Database operation failed: " + type(error).__name__) from None


if __name__ == "__main__":
    main()
