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
    tool_calls_delta: list[dict] | None = None


class OpenAICompatibleProvider:
    """OpenAI 兼容 chat/completions 流式调用。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float):
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
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
                if delta.get("tool_calls"):
                    yield StreamChunk(tool_calls_delta=delta["tool_calls"])
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

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        last_message = messages[-1] if messages else {}
        last = str(last_message.get("content") or "")
        if last_message.get("role") == "tool":
            tool_results: list[str] = []
            for item in reversed(messages):
                if item.get("role") != "tool":
                    break
                tool_results.append(str(item.get("content") or ""))
            reply = "（Mock 工具回复）" + "\n".join(reversed(tool_results))
            async for chunk in self._stream_reply(reply):
                yield chunk
            return

        available = {
            str(item.get("function", {}).get("name")) for item in (tools or [])
        }
        selected = self._select_tool(last, available)
        if selected is not None:
            name, arguments = selected
            yield StreamChunk(
                tool_calls_delta=[
                    {
                        "index": 0,
                        "id": f"mock-{name}-call",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                ]
            )
            yield StreamChunk(
                finish_reason="tool_calls",
                usage={"prompt_tokens": 8, "completion_tokens": 4},
            )
            return

        reply = (
            f"（Mock 回复）收到：{last[:60]}\n\n"
            "这是 P0 联调用的 Mock 模型回复。在 .env 中配置 LLM_PROVIDER=openai-compatible "
            "与 LLM_API_KEY 后即可切换到真实模型。"
        )
        if any('citation_id="c1"' in item.get("content", "") for item in messages):
            reply += " [c1]"
        async for chunk in self._stream_reply(reply):
            yield chunk

    async def _stream_reply(self, reply: str) -> AsyncIterator[StreamChunk]:
        for i in range(0, len(reply), 4):
            yield StreamChunk(text=reply[i : i + 4])
            await asyncio.sleep(self.delay)
        yield StreamChunk(
            finish_reason="stop",
            usage={"prompt_tokens": 8, "completion_tokens": len(reply) // 2},
        )

    @staticmethod
    def _select_tool(text: str, available: set[str]) -> tuple[str, dict] | None:
        if "get_time" in available and any(token in text for token in ("时间", "几点", "日期")):
            return "get_time", {}
        if "calculate" in available and "计算" in text:
            expression = text.split("计算", 1)[1].strip(" ：:，,。") or "0"
            return "calculate", {"expression": expression}
        if "read_file" in available and any(token in text for token in ("读取文件", "查看笔记")):
            match = re.search(r"(?:读取文件|查看笔记)[：:\s]*([^，。\s]+)", text)
            return "read_file", {"path": match.group(1) if match else "notes.md"}
        if "write_file" in available and any(token in text for token in ("写入", "保存笔记")):
            match = re.search(r"(?:写入|保存笔记)[：:\s]*(.*)", text, flags=re.DOTALL)
            content = (match.group(1) if match else text).strip() or text
            return "write_file", {"path": "notes.md", "content": content}
        return None

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
