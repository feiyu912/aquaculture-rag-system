from __future__ import annotations

import pytest

from app.config import Settings
from app.generation.llm import LLMError, MockGenerator, build_generator


def test_deepseek_without_key_raises_instead_of_mocking():
    config = Settings(llm_provider="deepseek", deepseek_api_key="")
    with pytest.raises(LLMError):
        build_generator(config)


def test_mock_provider_returns_mock_generator():
    assert isinstance(build_generator(Settings(llm_provider="mock")), MockGenerator)


def test_openai_compatible_without_endpoint_raises_instead_of_mocking():
    config = Settings(
        llm_provider="openai_compatible",
        openai_api_key="x",
        openai_base_url="",
        openai_model="",
    )
    with pytest.raises(LLMError):
        build_generator(config)
