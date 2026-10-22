from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import manage
from app.config import Settings
from app.models import AppSetting
from app.runtime_settings import LLM_MODEL_KEY, apply_llm_override, env_llm_model
from app.schemas import LlmModelUpdate


def test_env_llm_model_uses_openai_model_for_gateway_provider():
    config = Settings(
        llm_provider="openai_compatible",
        openai_api_key="x",
        openai_base_url="https://gw.example/v1",
        openai_model="deepseek-v4.1-flash",
    )
    assert env_llm_model(config) == "deepseek-v4.1-flash"


def test_env_llm_model_uses_deepseek_model_for_deepseek_provider():
    config = Settings(llm_provider="deepseek", deepseek_api_key="x", deepseek_model="deepseek-chat")
    assert env_llm_model(config) == "deepseek-chat"


def test_env_llm_model_falls_back_to_provider_name():
    assert env_llm_model(Settings(llm_provider="mock")) == "mock"


def test_apply_llm_override_updates_model():
    config = Settings(
        llm_provider="openai_compatible",
        openai_api_key="x",
        openai_base_url="https://gw.example/v1",
        openai_model="deepseek-v4.1-flash",
    )
    patched = apply_llm_override(config, "another-model")
    assert patched.openai_model == "another-model"
    assert patched is not config


def test_apply_llm_override_none_is_noop():
    config = Settings(
        llm_provider="openai_compatible",
        openai_api_key="x",
        openai_base_url="https://gw.example/v1",
        openai_model="m1",
    )
    assert apply_llm_override(config, None) is config


class FakeDB:
    def __init__(self) -> None:
        self.rows: dict[str, AppSetting] = {}

    async def get(self, model: object, key: str) -> AppSetting | None:
        return self.rows.get(key)

    def add(self, row: AppSetting) -> None:
        self.rows[row.key] = row

    async def delete(self, row: AppSetting) -> None:
        self.rows.pop(row.key, None)

    async def commit(self) -> None:
        return None


async def test_put_llm_rejects_mock_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manage.settings, "llm_provider", "mock")
    with pytest.raises(HTTPException) as exc:
        await manage.set_llm_config(LlmModelUpdate(model="any", ping=False), FakeDB())
    assert exc.value.status_code == 400


async def test_put_llm_pings_then_saves(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manage.settings, "llm_provider", "openai_compatible")
    called: dict[str, str] = {}

    async def fake_ping(model: str) -> None:
        called["model"] = model

    monkeypatch.setattr(manage, "_ping_model", fake_ping)
    db = FakeDB()
    await manage.set_llm_config(LlmModelUpdate(model="new-model", ping=True), db)
    assert called["model"] == "new-model"
    assert db.rows[LLM_MODEL_KEY].value == "new-model"


async def test_put_llm_ping_failure_does_not_save(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manage.settings, "llm_provider", "openai_compatible")

    async def bad_ping(model: str) -> None:
        raise RuntimeError("gateway HTTP 404")

    monkeypatch.setattr(manage, "_ping_model", bad_ping)
    db = FakeDB()
    with pytest.raises(HTTPException) as exc:
        await manage.set_llm_config(LlmModelUpdate(model="bad-model", ping=True), db)
    assert exc.value.status_code == 400
    assert "gateway HTTP 404" in str(exc.value.detail)
    assert LLM_MODEL_KEY not in db.rows


async def test_put_llm_empty_clears_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manage.settings, "llm_provider", "openai_compatible")
    db = FakeDB()
    db.rows[LLM_MODEL_KEY] = AppSetting(key=LLM_MODEL_KEY, value="old-model")
    await manage.set_llm_config(LlmModelUpdate(model="  ", ping=False), db)
    assert LLM_MODEL_KEY not in db.rows


async def test_put_llm_rejects_invalid_model_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manage.settings, "llm_provider", "openai_compatible")
    with pytest.raises(HTTPException) as exc:
        await manage.set_llm_config(LlmModelUpdate(model="has space", ping=False), FakeDB())
    assert exc.value.status_code == 400


async def test_get_llm_reports_effective_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manage.settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(manage.settings, "openai_model", "env-model")
    db = FakeDB()
    db.rows[LLM_MODEL_KEY] = AppSetting(key=LLM_MODEL_KEY, value="override-model")
    info = await manage.get_llm_config(db)
    assert info["env_model"] == "env-model"
    assert info["override_model"] == "override-model"
    assert info["effective_model"] == "override-model"
    assert info["switchable"] is True


async def test_get_llm_without_override_uses_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manage.settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(manage.settings, "openai_model", "env-model")
    info = await manage.get_llm_config(FakeDB())
    assert info["override_model"] is None
    assert info["effective_model"] == "env-model"
