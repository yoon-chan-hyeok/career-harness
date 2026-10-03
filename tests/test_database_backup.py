import importlib.util
import sqlite3
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "database_backup.py"
    spec = importlib.util.spec_from_file_location("database_backup", path)
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_sqlite_backup_restore_checks_hash_and_refuses_nonempty_target(tmp_path):
    operation = module()
    source, target, backup = tmp_path / "source.db", tmp_path / "target.db", tmp_path / "saved.backup"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sources(id TEXT, body TEXT)")
        connection.execute("INSERT INTO sources VALUES ('source-a','private document')")
    result = operation.backup("sqlite:///" + str(source), backup)
    assert result["contains_private_data"] and operation.validate_backup(backup)["sha256"]
    with pytest.raises(ValueError):
        operation.restore("sqlite:///" + str(target), backup, False)
    operation.restore("sqlite:///" + str(target), backup, True)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT body FROM sources").fetchone() == ("private document",)
    with pytest.raises(ValueError, match="contains application data"):
        operation.restore("sqlite:///" + str(target), backup, True)
    backup.write_bytes(backup.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="checksum"):
        operation.validate_backup(backup)


def test_postgres_credentials_are_passed_by_environment_only():
    operation = module()
    values = operation.pg_environment(
        "postgres://owner:p%40ss@db.example/postgres?sslmode=verify-full&sslrootcert=/run/secrets/ca.crt"
    )
    assert values["PGPASSWORD"] == "p@ss"
    assert values["PGSSLMODE"] == "verify-full"
    assert values["PGSSLROOTCERT"] == "/run/secrets/ca.crt"
