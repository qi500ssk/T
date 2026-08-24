import json

import pytest

from core.chat.intent import narrow_allowed_tools, route_intent, rule_intent


class SpyProvider:
    def __init__(self, result: dict | None = None):
        self.calls = 0
        self.result = result or {}

    async def complete(self, messages, temperature=0.0):
        self.calls += 1
        return json.dumps(self.result, ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("你好", "conversation"),
        ("计算 122+22", "calculation"),
        ("现在几点", "current_information"),
        ("查看我的记忆", "memory_management"),
        ("根据上传的文档回答", "knowledge_query"),
        ("修改项目里的 API 测试", "software_development"),
        ("设置模型上下文", "settings_change"),
        ("保存备忘录：今天买牛奶", "task_execution"),
    ],
)
async def test_rule_routes_do_not_call_model(message, expected):
    provider = SpyProvider()
    result = await route_intent(message, provider)
    assert result.intent == expected
    assert result.source == "rule"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_ambiguous_request_uses_classifier_when_confident():
    provider = SpyProvider(
        {
            "intent": "software_development",
            "action": "inspect_project",
            "needs_memory": True,
            "needs_knowledge": False,
            "needs_workspace": True,
            "needs_plan": True,
            "candidate_tools": ["code_search", "invented_tool"],
            "risk_hint": "medium",
            "confidence": 0.91,
        }
    )
    result = await route_intent("帮我看看这个", provider)
    assert result.intent == "software_development"
    assert result.source == "model"
    assert provider.calls == 1
    assert narrow_allowed_tools(result, {"code_search", "get_time"}) == {
        "code_search",
        "get_time",
    }


@pytest.mark.asyncio
async def test_low_confidence_classifier_safely_falls_back():
    provider = SpyProvider(
        {
            "intent": "task_execution",
            "action": "execute",
            "needs_memory": True,
            "needs_knowledge": False,
            "needs_workspace": True,
            "needs_plan": True,
            "candidate_tools": ["write_file"],
            "risk_hint": "high",
            "confidence": 0.4,
        }
    )
    result = await route_intent("请帮我处理一下这个", provider)
    assert result.intent == "conversation"
    assert result.source == "model_fallback"
    assert narrow_allowed_tools(result, {"write_file"}) == {"write_file"}


def test_rule_router_returns_none_for_normal_conversation():
    assert rule_intent("我最近在考虑换一种工作方式") is None


def test_capability_question_is_conversation_not_development_task():
    result = rule_intent("你现在能写前端界面吗")
    assert result is not None
    assert result.intent == "conversation"
    assert result.action == "explain_capability"
    assert result.needs_plan is False


def test_dynamic_current_information_keeps_existing_whitelist_without_expanding_it():
    result = rule_intent("今天最新的天气")
    assert result is not None and result.intent == "current_information"
    assert narrow_allowed_tools(result, {"browser_search", "get_time"}) == {
        "browser_search",
        "get_time",
    }


@pytest.mark.parametrize(
    ("message", "action", "tools"),
    [
        ("请记住我喜欢无糖拿铁", "create_memory", {"memory_create"}),
        ("查看你记住了什么", "list_memories", {"memory_list"}),
        (
            "把你记住的数据库改成 PostgreSQL",
            "update_memory",
            {"memory_list", "memory_update"},
        ),
        ("不要记住我刚才说的内容", "forget_memory", {"memory_list", "memory_forget"}),
    ],
)
def test_explicit_memory_operations_have_deterministic_routes(message, action, tools):
    result = rule_intent(message)
    assert result is not None
    assert result.intent == "memory_management"
    assert result.action == action
    assert narrow_allowed_tools(
        result,
        {"memory_list", "memory_create", "memory_update", "memory_forget", "write_file"},
    ) == tools


def test_memory_explanation_does_not_mutate_memory():
    result = rule_intent("语义记忆和长期记忆有什么区别")
    assert result is not None
    assert result.intent == "conversation"
    assert result.action == "explain_memory"
