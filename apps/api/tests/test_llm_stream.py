from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.generation.llm import ChatCompletionsGenerator, LLMError


def _generator(frames: str) -> ChatCompletionsGenerator:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=frames.encode("utf-8"))

    return ChatCompletionsGenerator(
        settings,
        api_key="test-key",
        base_url="http://test.local",
        model="test-model",
        name="openai_compatible",
        transport=httpx.MockTransport(handler),
    )


async def _collect(generator: ChatCompletionsGenerator) -> str:
    return "".join([token async for token in generator.stream("q", [])])


def _frame(payload: str) -> str:
    return f"data: {payload}\n\n"


async def test_stream_accepts_done_and_stop_reason():
    frames = (
        _frame('{"choices":[{"delta":{"content":"你好"}}]}')
        + _frame('{"choices":[{"delta":{},"finish_reason":"stop"}]}')
        + _frame("[DONE]")
    )
    assert await _collect(_generator(frames)) == "你好"


async def test_stream_accepts_finish_reason_stop_without_done_sentinel():
    frames = _frame('{"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}')
    assert await _collect(_generator(frames)) == "ok"


async def test_stream_rejects_truncated_length_finish_without_done_sentinel():
    frames = _frame('{"choices":[{"delta":{"content":"半句"},"finish_reason":"length"}]}')
    generator = _generator(frames)
    tokens: list[str] = []
    with pytest.raises(LLMError, match="length"):
        async for token in generator.stream("q", []):
            tokens.append(token)
    # Partial text stays available to the caller so it can persist a failed
    # message with the partial answer instead of losing it.
    assert tokens == ["半句"]


async def test_stream_rejects_eof_without_done_or_finish_reason():
    frames = _frame('{"choices":[{"delta":{"content":"x"}}]}')
    with pytest.raises(LLMError, match="without \\[DONE\\]"):
        await _collect(_generator(frames))


async def test_stream_surfaces_error_frames():
    frames = _frame('{"error":{"message":"quota exceeded"}}')
    with pytest.raises(LLMError, match="quota exceeded"):
        await _collect(_generator(frames))