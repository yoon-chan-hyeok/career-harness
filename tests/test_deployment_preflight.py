import argparse
import importlib.util
import json
import runpy
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from career import decisions, providers


def preflight_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "deployment_preflight.py"
    spec = importlib.util.spec_from_file_location("deployment_preflight", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def options(**overrides):
    return argparse.Namespace(**{
        "check_database": False,
        "check_public_keys": False,
        "live_ai": False,
        "live_openai": False,
        "live_jev": False,
        **overrides,
    })


def test_default_preflight_never_initializes_external_providers(monkeypatch):
    operation = preflight_module()
    monkeypatch.setattr(operation, "validate_runtime_settings", lambda: None)

    def unexpected(*args, **kwargs):
        raise AssertionError("Default preflight must not access external services")

    monkeypatch.setattr(providers, "configured_provider", unexpected)
    monkeypatch.setattr(providers, "OpenAIProvider", unexpected)
    monkeypatch.setattr(decisions, "JevDecisionProvider", unexpected)
    monkeypatch.setattr(operation, "readiness", unexpected)
    monkeypatch.setattr(operation, "configured_verifier", unexpected)
    assert operation.run(options()) == {"status": "ok", "checks": {"configuration": {"status": "ok"}}}


@pytest.mark.parametrize("answer", [True, False])
def test_selected_provider_probe_uses_only_synthetic_context(monkeypatch, answer):
    operation = preflight_module()
    monkeypatch.setattr(operation, "validate_runtime_settings", lambda: None)
    calls = []
    factories = []

    def structured(prompt_id, context, schema):
        calls.append((prompt_id, context, schema))
        return schema(ok=answer)

    def selected():
        factories.append(True)
        return SimpleNamespace(structured=structured)

    monkeypatch.setattr(providers, "configured_provider", selected)
    report = operation.run(options(live_ai=True))
    assert factories == [True]
    assert calls == [("deployment_probe", {"synthetic": "Return ok=true."}, operation.ProbeResponse)]
    assert report["checks"]["selected_ai"] == {
        "status": "ok" if answer else "failed", "live_verified": True,
    }
    assert report["status"] == ("ok" if answer else "not_ready")
    assert "openai" not in report["checks"] and "jev" not in report["checks"]


@pytest.mark.parametrize("failure_stage", ["factory", "response"])
def test_selected_provider_failure_redacts_exception_credentials(monkeypatch, failure_stage):
    operation = preflight_module()
    monkeypatch.setattr(operation, "validate_runtime_settings", lambda: None)
    secret = "hf_synthetic_private_key_never_print"
    calls = []

    def failed(*args, **kwargs):
        calls.append(True)
        raise RuntimeError(f"Authorization: Bearer {secret}")

    monkeypatch.setattr(providers, "configured_provider", failed if failure_stage == "factory" else
                        lambda: SimpleNamespace(structured=failed))
    report = operation.run(options(live_ai=True))
    assert calls == [True]
    assert report["status"] == "not_ready"
    assert report["checks"]["selected_ai"] == {"status": "failed", "error_type": "RuntimeError"}
    assert secret not in json.dumps(report) and "Authorization" not in json.dumps(report)


def test_legacy_live_openai_probe_remains_independent(monkeypatch):
    operation = preflight_module()
    monkeypatch.setattr(operation, "validate_runtime_settings", lambda: None)
    calls = []

    def selected():
        raise AssertionError("The legacy probe must not select an HF/Groq provider")

    def structured(prompt_id, context, schema):
        calls.append(context)
        return schema(ok=True)

    monkeypatch.setattr(providers, "configured_provider", selected)
    monkeypatch.setattr(providers, "OpenAIProvider", lambda: SimpleNamespace(structured=structured))
    report = operation.run(options(live_openai=True))
    assert report["status"] == "ok"
    assert report["checks"]["openai"] == {"status": "ok", "live_verified": True}
    assert "selected_ai" not in report["checks"]
    assert calls == [{"synthetic": "Return ok=true."}]


def test_default_cli_does_not_enable_live_probes(monkeypatch, capsys):
    operation = preflight_module()
    monkeypatch.setattr(operation, "validate_runtime_settings", lambda: None)
    monkeypatch.setattr(operation.sys, "argv", ["deployment_preflight.py"])
    with pytest.raises(SystemExit) as result:
        operation.main()
    assert result.value.code == 0
    assert json.loads(capsys.readouterr().out)["checks"] == {"configuration": {"status": "ok"}}


@pytest.mark.parametrize("path", [
    ".provider-settings.json",
    "nested/.provider-settings.json",
    ".provider-settings.json.synthetic.tmp",
    "nested/.provider-settings.json.synthetic.tmp",
])
def test_privacy_check_rejects_tracked_provider_credentials(monkeypatch, path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_privacy.py"
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: f"README.md\n{path}\n")
    with pytest.raises(SystemExit, match="Private paths tracked"):
        runpy.run_path(str(script))


def test_privacy_check_allows_public_environment_templates(monkeypatch, capsys):
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_privacy.py"
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs:
                        ".env.example\ndeploy/backend.env.example\nprivate_input/.gitkeep\n")
    runpy.run_path(str(script))
    assert capsys.readouterr().out.strip() == "Privacy check passed"


def docker_privacy_check(monkeypatch):
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_privacy.py"
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "")
    return runpy.run_path(str(script))["check_docker_provider_exclusions"]


@pytest.mark.parametrize("removed", [".provider-settings.json", ".provider-settings.json.*.tmp"])
def test_docker_context_rejects_missing_private_exclusion(monkeypatch, tmp_path, removed):
    check = docker_privacy_check(monkeypatch)
    actual = Path(__file__).resolve().parents[1] / ".dockerignore"
    modified = "\n".join(line for line in actual.read_text().splitlines() if line != removed)
    (tmp_path / ".dockerignore").write_text(modified, encoding="utf-8")
    with pytest.raises(SystemExit, match="Docker build context"):
        check(tmp_path)


def test_docker_context_rejects_later_reinclusion(monkeypatch, tmp_path):
    check = docker_privacy_check(monkeypatch)
    actual = Path(__file__).resolve().parents[1] / ".dockerignore"
    (tmp_path / ".dockerignore").write_text(actual.read_text() + "\n!*.json\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="Docker build context"):
        check(tmp_path)


def test_docker_context_requires_readable_exclusion_file(monkeypatch, tmp_path):
    check = docker_privacy_check(monkeypatch)
    with pytest.raises(SystemExit, match="Docker privacy exclusions could not be checked"):
        check(tmp_path)
