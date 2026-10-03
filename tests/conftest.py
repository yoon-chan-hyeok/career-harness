import pytest
from career import models  # noqa: F401
from career.db import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def isolate_real_provider_credentials(monkeypatch, tmp_path):
    """Regression tests must never spend the owner's credits or edit their tokens."""
    from career import provider_config

    monkeypatch.setattr(provider_config, "SETTINGS_PATH", tmp_path / "provider-settings.json")
    monkeypatch.setattr(provider_config, "LOCAL_SETTINGS_PATH", tmp_path / "owner-settings.json")
    for key in (
        "CAREER_LLM_PROVIDER", "HF_TOKEN", "HF_MODEL", "HF_FREE_ONLY_CONFIRMED",
        "GROQ_API_KEY", "GROQ_MODEL", "GROQ_FREE_ONLY_CONFIRMED", "OPENAI_API_KEY", "OPENAI_MODEL",
        "CAREER_LLM_SMALL_MODEL", "CAREER_LLM_STAGE_POLICIES", "CAREER_LLM_PRICING_JSON",
        "CAREER_LLM_TIMEOUT_SECONDS", "CAREER_LLM_MAX_OUTPUT_TOKENS", "JEV_API_KEY", "JEV_SHADOW_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()
