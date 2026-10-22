from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.models import AppSetting

LLM_MODEL_KEY = "llm_model"


def env_llm_model(config: Settings = settings) -> str:
    if config.llm_provider == "deepseek":
        return config.deepseek_model
    if config.llm_provider in {"openai_compatible", "openai"}:
        return config.openai_model or config.llm_provider
    return "mock"


def apply_llm_override(config: Settings, override: str | None) -> Settings:
    if not override:
        return config
    return config.model_copy(update={"openai_model": override, "deepseek_model": override})


async def get_setting(db: AsyncSession, key: str) -> str | None:
    row = await db.get(AppSetting, key)
    return row.value if row else None


async def set_setting(db: AsyncSession, key: str, value: str | None) -> None:
    row = await db.get(AppSetting, key)
    if value:
        if row is not None:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))
    elif row is not None:
        await db.delete(row)
    await db.commit()
