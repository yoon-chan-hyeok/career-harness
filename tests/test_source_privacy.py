"""Reject private files before a first source commit, including future forced adds."""
import json
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def privacy():
    return runpy.run_path(str(PROJECT / "scripts/check_privacy.py"))


@pytest.mark.parametrize("relative", [
    ".provider-settings.json", "nested/.local-settings.json", "nested/secret.env",
    "private_input/resume.txt", "nested/career.db-wal", "nested/career.sqlite-shm",
    "work/backup.dump", "nested/owner.key", "nested/owner.pem", "ui-dashboard.png",
    "source_specs/개인_작성전략_v4_Canonical.txt",
])
def test_untracked_private_file_in_unborn_repository_is_rejected(privacy, tmp_path, relative):
    if not shutil.which("git"):
        pytest.skip("Git is required for source candidate verification")
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("synthetic private content", encoding="utf-8")
    with pytest.raises(SystemExit, match="Private paths tracked or eligible") as error:
        privacy["check_source_candidates"](tmp_path)
    assert "synthetic private content" not in str(error.value)


def test_ignored_private_file_is_still_rejected_when_forced_into_git(privacy, tmp_path):
    if not shutil.which("git"):
        pytest.skip("Git is required for source candidate verification")
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / ".gitignore").write_text("*.key\n", encoding="utf-8")
    (tmp_path / "owner.key").write_text("synthetic", encoding="utf-8")
    privacy["check_source_candidates"](tmp_path)
    subprocess.run(["git", "add", "--force", "owner.key"], cwd=tmp_path, check=True, capture_output=True)
    with pytest.raises(SystemExit, match="Private paths tracked or eligible"):
        privacy["check_source_candidates"](tmp_path)


def test_imported_history_cannot_replace_public_regressions(privacy, tmp_path):
    (tmp_path / "evals").mkdir()
    path = tmp_path / "evals/historical_cases.jsonl"
    path.write_text(json.dumps({"source_id": "private-history", "input": "synthetic secret"}), encoding="utf-8")
    with pytest.raises(SystemExit, match="reviewed synthetic cases") as error:
        privacy["check_public_regressions"](tmp_path)
    assert "synthetic secret" not in str(error.value)


def test_public_fixture_has_explicit_synthetic_provenance(privacy):
    privacy["check_public_regressions"](PROJECT)
    cases = [json.loads(line) for line in (PROJECT / "evals/historical_cases.jsonl").read_text("utf-8").splitlines()]
    assert len(cases) == 8
    assert all(case["id"].startswith("synthetic-") for case in cases)
