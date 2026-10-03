# ruff: noqa: F811 -- reusable authenticated API fixture
import json
from typing import Literal

import pytest
from career import provider_config
from career.provider_config import (
    ProviderConfigRequest,
    configure_provider,
    note_verification,
    provider_available,
    provider_settings,
    provider_status,
)
from fastapi import HTTPException
from test_api import client  # noqa: F401

SECRET = "hf_synthetic_test_key_private"


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(provider_config, "SETTINGS_PATH", tmp_path / ".provider-settings.json")
    owner = tmp_path / ".local-settings.json"
    owner.write_text(json.dumps({"user": "alice", "token": "synthetic-local-auth"}), "utf-8-sig")
    monkeypatch.setattr(provider_config, "LOCAL_SETTINGS_PATH", owner)
    monkeypatch.setattr(provider_config, "_MEMORY_VERIFICATION", None)
    monkeypatch.setenv("CAREER_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "local")
    for name in (
        "CAREER_LLM_PROVIDER", "HF_TOKEN", "HF_MODEL", "HF_FREE_ONLY_CONFIRMED",
        "GROQ_API_KEY", "GROQ_MODEL", "GROQ_FREE_ONLY_CONFIRMED", "OPENAI_API_KEY", "OPENAI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def configuration(provider: Literal["none", "huggingface", "groq"] = "huggingface", model="", token=SECRET, free=True):
    return ProviderConfigRequest(provider=provider, model=model, token=token, free_only_confirmed=free)


def test_local_profiles_preserve_keys_and_no_automatic_live_verification():
    first = configure_provider("alice", configuration())
    assert first["provider"] == "huggingface"
    assert first["model"] == "openai/gpt-oss-120b:fireworks-ai"
    assert first["configured"] and first["editable"]
    assert first["credential_source"] == "local_private_file"
    assert not first["live_verified"] and first["verified_at"] is None
    assert SECRET not in repr(provider_settings())
    assert SECRET not in json.dumps(first)
    configure_provider("alice", configuration("groq", token="synthetic_groq_key"))
    configure_provider("alice", configuration("none", token=""))
    assert not provider_available()
    configure_provider("alice", configuration(token="", model="Qwen/Qwen3-32B:fireworks-ai"))
    assert provider_settings().token == SECRET
    assert provider_settings().model == "Qwen/Qwen3-32B:fireworks-ai"
    saved = json.loads(provider_config.SETTINGS_PATH.read_text("utf-8"))
    assert set(saved["profiles"]) == {"huggingface", "groq"}
    assert not list(provider_config.SETTINGS_PATH.parent.glob(".provider-settings.json.*.tmp"))


def test_free_only_confirmation_required_before_third_party_is_available():
    configure_provider("alice", configuration(free=False))
    assert provider_settings().token == SECRET
    assert not provider_available()
    assert not provider_status("alice")["configured"]
    configure_provider("alice", configuration(free=True, token=""))
    assert provider_available()


def test_environment_selection_overrides_private_and_legacy_and_is_read_only(monkeypatch):
    configure_provider("alice", configuration())
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic_openai_key")
    monkeypatch.setenv("OPENAI_MODEL", "explicit-openai-model")
    monkeypatch.setenv("CAREER_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic_environment_groq")
    monkeypatch.setenv("GROQ_FREE_ONLY_CONFIRMED", "1")
    settings = provider_settings()
    assert settings.provider == "groq" and settings.model == "openai/gpt-oss-120b"
    assert settings.credential_source == "server_environment"
    assert not provider_status("alice")["editable"]
    with pytest.raises(HTTPException) as error:
        configure_provider("alice", configuration("none"))
    assert error.value.status_code == 403
    monkeypatch.setenv("CAREER_LLM_PROVIDER", "none")
    assert not provider_available()
    assert not provider_status("alice")["editable"]


def test_private_selection_overrides_legacy_and_server_credential_cannot_be_edited(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic_openai")
    monkeypatch.setenv("OPENAI_MODEL", "explicit-legacy-model")
    assert provider_settings().provider == "openai"
    assert not provider_status("alice")["editable"]
    # A separately provisioned private profile takes precedence over legacy selection.
    provider_config.SETTINGS_PATH.write_text(
        json.dumps({"selected_provider": "huggingface", "profiles": {
            "huggingface": {"model": "repo/model:fireworks-ai", "token": SECRET, "free_only_confirmed": True}
        }}), "utf-8",
    )
    assert provider_settings().provider == "huggingface"
    monkeypatch.setenv("HF_TOKEN", "synthetic_environment_hf")
    assert provider_settings().token == "synthetic_environment_hf"
    assert not provider_status("alice")["editable"]


@pytest.mark.parametrize("environment,auth", [("production", "local"), ("staging", "local"), ("test", "supabase")])
def test_non_local_environments_do_not_load_private_credentials_or_allow_edits(monkeypatch, environment, auth):
    configure_provider("alice", configuration())
    monkeypatch.setenv("CAREER_ENV", environment)
    monkeypatch.setenv("AUTH_MODE", auth)
    assert provider_settings().provider == "none"
    assert not provider_status("alice")["editable"]
    with pytest.raises(HTTPException) as error:
        configure_provider("alice", configuration())
    assert error.value.status_code == 403


def test_live_verification_binds_provider_model_key_consent_and_clears_on_failure(monkeypatch):
    configure_provider("alice", configuration())
    snapshot = provider_settings()
    note_verification(True, expected=snapshot)
    assert provider_status("alice")["live_verified"]
    assert provider_status("alice")["verified_at"]
    monkeypatch.setattr(provider_config, "_MEMORY_VERIFICATION", None)
    assert provider_status("alice")["live_verified"]  # Restored verification metadata.
    monkeypatch.setenv("HF_TOKEN", "synthetic_rotated_token")
    assert not provider_status("alice")["live_verified"]
    note_verification(True, expected=snapshot)
    assert not provider_status("alice")["live_verified"]
    note_verification(True)
    assert provider_status("alice")["live_verified"]
    note_verification(False)
    assert not provider_status("alice")["live_verified"]
    assert provider_status("alice")["verified_at"] is None


def test_read_is_bounded_and_errors_never_echo_private_file_or_token():
    provider_config.SETTINGS_PATH.write_text(SECRET * 5000, "utf-8")
    with pytest.raises(ValueError) as error:
        provider_settings()
    assert SECRET not in str(error.value)
    assert str(provider_config.SETTINGS_PATH) not in str(error.value)
    assert not provider_available()


@pytest.mark.parametrize("payload", [
    {"selected_provider": "huggingface", "unexpected": SECRET},
    {"selected_provider": "huggingface", "profiles": {"other": {"model": "x"}}},
    {"selected_provider": "huggingface", "profiles": {"huggingface": {"model": "x", "free_only_confirmed": "true"}}},
])
def test_private_file_rejects_unknown_fields_providers_and_coerced_types(payload):
    provider_config.SETTINGS_PATH.write_text(json.dumps(payload), "utf-8")
    with pytest.raises(ValueError) as error:
        provider_settings()
    assert SECRET not in str(error.value)


def test_atomic_failure_preserves_previous_private_profile(monkeypatch):
    configure_provider("alice", configuration())
    old = provider_config.SETTINGS_PATH.read_bytes()

    def fail_replace(*_args):
        raise OSError("synthetic failure containing " + SECRET)

    monkeypatch.setattr(provider_config.os, "replace", fail_replace)
    with pytest.raises(ValueError) as error:
        configure_provider("alice", configuration(model="repo/new-model"))
    assert SECRET not in str(error.value)
    assert provider_config.SETTINGS_PATH.read_bytes() == old
    assert not list(provider_config.SETTINGS_PATH.parent.glob(".provider-settings.json.*.tmp"))


def test_environment_status_does_not_depend_on_corrupt_local_profile(monkeypatch):
    provider_config.SETTINGS_PATH.write_text(SECRET * 5000, "utf-8")
    original = provider_config.SETTINGS_PATH.read_bytes()
    monkeypatch.setenv("CAREER_LLM_PROVIDER", "huggingface")
    monkeypatch.setenv("HF_TOKEN", SECRET)
    monkeypatch.setenv("HF_FREE_ONLY_CONFIRMED", "1")
    assert provider_status("alice")["configured"]
    assert not provider_status("alice")["live_verified"]
    note_verification(True)
    assert provider_status("alice")["live_verified"]
    assert provider_config.SETTINGS_PATH.read_bytes() == original


def test_failed_probe_clears_previous_live_state_even_if_persistence_fails(monkeypatch):
    configure_provider("alice", configuration())
    note_verification(True)
    assert provider_status("alice")["live_verified"]

    def fail_replace(*_args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(provider_config.os, "replace", fail_replace)
    with pytest.raises(ValueError):
        note_verification(False)
    assert not provider_status("alice")["live_verified"]


def test_provider_routes_auth_owner_isolation_and_validation_redaction(client):
    body = {"provider": "huggingface", "model": "", "token": SECRET, "free_only_confirmed": True}
    assert client.get("/api/providers").status_code == 401
    assert client.post("/api/providers/configure", json=body).status_code == 401
    client.headers["Authorization"] = "Bearer bob-key"
    assert not client.get("/api/providers").json()["editable"]
    assert client.post("/api/providers/configure", json=body).status_code == 403
    assert client.post("/api/providers/check", json={}).status_code == 403
    client.headers["Authorization"] = "Bearer alice-key"
    good = client.post("/api/providers/configure", json=body)
    assert good.status_code == 200 and good.json()["configured"]
    assert SECRET not in good.text
    assert client.get("/api/settings").json()["ai_available"]
    for invalid in ({**body, "token": SECRET + "\n"}, {**body, "endpoint": SECRET}, {**body, "free_only_confirmed": "true"}):
        response = client.post("/api/providers/configure", json=invalid)
        assert response.status_code == 422 and SECRET not in response.text
    assert not client.get("/api/providers").json()["live_verified"]


def test_explicit_check_uses_only_synthetic_data_and_redacts_output_and_failures(client, monkeypatch):
    import career.providers as providers

    client.headers["Authorization"] = "Bearer alice-key"
    configure_provider("alice", configuration())
    calls = []

    class SyntheticProvider:
        def structured(self, stage, context, schema):
            calls.append((stage, context))
            return schema.model_validate({"message": "안녕하세요 " + SECRET})

    monkeypatch.setattr(providers, "configured_provider", lambda: SyntheticProvider(), raising=False)
    assert client.get("/api/providers").status_code == 200
    assert not calls
    checked = client.post("/api/providers/check", json={})
    assert checked.status_code == 200 and checked.json()["live_verified"]
    assert SECRET not in checked.text
    assert len(calls) == 1 and calls[0][0] == "provider_connection_check"
    assert set(calls[0][1]) == {"task"}
    assert SECRET not in json.dumps(calls)

    def broken():
        raise RuntimeError("Authorization: Bearer " + SECRET)

    monkeypatch.setattr(providers, "configured_provider", broken)
    failed = client.post("/api/providers/check", json={})
    assert failed.status_code == 200 and not failed.json()["live_verified"]
    assert failed.json()["verified_at"] is None and SECRET not in failed.text


def test_config_changed_during_check_cannot_verify_new_model(client, monkeypatch):
    import career.providers as providers

    client.headers["Authorization"] = "Bearer alice-key"
    configure_provider("alice", configuration())

    class ChangingProvider:
        def structured(self, _stage, _context, schema):
            configure_provider("alice", configuration(model="repo/changed-model", token=""))
            return schema.model_validate({"message": "안녕하세요"})

    monkeypatch.setattr(providers, "configured_provider", lambda: ChangingProvider(), raising=False)
    response = client.post("/api/providers/check", json={})
    assert response.status_code == 200
    assert response.json()["model"] == "repo/changed-model"
    assert not response.json()["live_verified"]


def test_check_never_calls_paid_openai_or_unconfigured_provider(client, monkeypatch):
    import career.providers as providers

    client.headers["Authorization"] = "Bearer alice-key"
    calls = []
    monkeypatch.setattr(providers, "configured_provider", lambda: calls.append(True), raising=False)
    assert client.post("/api/providers/check", json={}).status_code == 503
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-commercial-key")
    monkeypatch.setenv("OPENAI_MODEL", "explicit-commercial-model")
    assert client.get("/api/providers").json()["provider"] == "openai"
    assert client.post("/api/providers/check", json={}).status_code == 503
    assert not calls
