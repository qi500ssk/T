import json

import httpx
import pytest

from core.chat.gateway import OpenAICompatibleProvider


async def _provider(model: str, handler) -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider(
        "https://models.example/v1",
        "test-key",
        model,
        10,
    )
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="https://models.example/v1",
        transport=httpx.MockTransport(handler),
    )
    return provider


@pytest.mark.asyncio
async def test_kimi_k3_omits_temperature_for_complete():
    captured = {}

    async def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    provider = await _provider("kimi-k3", handler)
    try:
        assert await provider.complete([{"role": "user", "content": "test"}], temperature=0.7) == "OK"
    finally:
        await provider.close()
    assert "temperature" not in captured


@pytest.mark.asyncio
async def test_kimi_k3_omits_temperature_for_stream():
    captured = {}

    async def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            content=(
                'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":null}]}\n\n'
                "data: [DONE]\n\n"
            ),
            headers={"Content-Type": "text/event-stream"},
        )

    provider = await _provider("kimi-k3", handler)
    try:
        chunks = [chunk async for chunk in provider.stream([{"role": "user", "content": "test"}])]
    finally:
        await provider.close()
    assert "".join(chunk.text for chunk in chunks) == "OK"
    assert "temperature" not in captured


@pytest.mark.asyncio
async def test_other_models_keep_temperature():
    captured = {}

    async def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    provider = await _provider("qwen3.8-max", handler)
    try:
        await provider.complete([{"role": "user", "content": "test"}], temperature=0.2)
    finally:
        await provider.close()
    assert captured["temperature"] == 0.2
