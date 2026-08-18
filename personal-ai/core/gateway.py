"""Model Gateway：业务代码不直接绑定具体模型 API。

P0 提供两个 provider：
- openai-compatible：OpenAI 兼容协议（可接 DeepSeek / Qwen / 智谱 / Ollama）
- mock：无 API Key 时的联调 provider
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import AsyncIterator

import httpx


@dataclass
class StreamChunk:
    text: str = ""
    finish_reason: str | None = None
    usage: dict | None = None


class OpenAICompatibleProvider:
    """OpenAI 兼容 chat/completions 流式调用。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float):
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def stream(self, messages: list[dict], temperature: float = 0.7) -> AsyncIterator[StreamChunk]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "stream_options": {"include_usage": True},
        }
        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", "ignore")[:300]
                raise RuntimeError(f"LLM API 错误 {resp.status_code}: {body}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                obj = json.loads(data)
                if obj.get("usage"):
                    yield StreamChunk(usage=obj["usage"])
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    yield StreamChunk(text=delta["content"])
                if choices[0].get("finish_reason"):
                    yield StreamChunk(finish_reason=choices[0]["finish_reason"])

    async def complete(self, messages: list[dict], temperature: float = 0.0) -> str:
        """非流式调用，供摘要和结构化记忆提取使用。"""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
        }
        response = await self._client.post("/chat/completions", json=payload)
        if response.status_code != 200:
            body = response.text[:300]
            raise RuntimeError(f"LLM API 错误 {response.status_code}: {body}")
        choices = response.json().get("choices") or []
        if not choices:
            raise RuntimeError("LLM API 未返回 choices")
        return str((choices[0].get("message") or {}).get("content") or "")

    async def close(self) -> None:
        await self._client.aclose()


class MockProvider:
    """无 API Key 时联调用：流式返回一段固定文本。"""

    def __init__(self, delay: float = 0.02):
        self.delay = delay

    async def stream(self, messages: list[dict], temperature: float = 0.7) -> AsyncIterator[StreamChunk]:
        last = messages[-1]["content"] if messages else ""
        reply = (
            f"（Mock 回复）收到：{last[:60]}\n\n"
            "这是 P0 联调用的 Mock 模型回复。在 .env 中配置 LLM_PROVIDER=openai-compatible "
            "与 LLM_API_KEY 后即可切换到真实模型。"
        )
        if any('citation_id="c1"' in item.get("content", "") for item in messages):
            reply += " [c1]"
        for i in range(0, len(reply), 4):
            yield StreamChunk(text=reply[i : i + 4])
            await asyncio.sleep(self.delay)
        yield StreamChunk(
            finish_reason="stop",
            usage={"prompt_tokens": 8, "completion_tokens": len(reply) // 2},
        )

    async def complete(self, messages: list[dict], temperature: float = 0.0) -> str:
        """为本地联调提供可预测的摘要和常见偏好提取。"""
        system = messages[0].get("content", "") if messages else ""
        content = messages[-1].get("content", "") if messages else ""
        if "MEMORY_EXTRACTION" in system:
            try:
                user_input = str(json.loads(content).get("user_input", ""))
            except (json.JSONDecodeError, AttributeError):
                user_input = content
            match = re.search(r"我(?:最)?喜欢([^，。！？\n]{1,40})", user_input)
            if not match:
                return '{"memories": []}'
            preference = match.group(1).strip()
            return json.dumps(
                {
                    "memories": [
                        {
                            "key": "preference." + re.sub(r"\s+", "", preference)[:40],
                            "kind": "profile",
                            "content": f"用户喜欢{preference}",
                            "importance": 4,
                            "confidence": 0.95,
                        }
                    ]
                },
                ensure_ascii=False,
            )
        if "CONVERSATION_SUMMARY" in system:
            compact = re.sub(r"\s+", " ", content).strip()
            return compact[-1200:]
        return ""

    async def close(self) -> None:
        pass


def build_provider(settings) -> OpenAICompatibleProvider | MockProvider:
    """按配置选择 provider。"""
    if settings.llm_provider == "openai-compatible":
        if not settings.llm_base_url or not settings.llm_api_key:
            raise ValueError("LLM_PROVIDER=openai-compatible 时需配置 LLM_BASE_URL 与 LLM_API_KEY")
        return OpenAICompatibleProvider(
            settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout_seconds
        )
    return MockProvider()
