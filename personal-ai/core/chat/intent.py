"""规则优先的统一意图路由；只负责缩小信息源和工具候选，不负责授权。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


PROMPT_FILE = Path(__file__).resolve().parents[2] / "prompts" / "intent" / "classify.md"
INTENTS = {
    "conversation",
    "knowledge_query",
    "memory_management",
    "software_development",
    "task_execution",
    "current_information",
    "calculation",
    "settings_change",
}

_GREETING = re.compile(
    r"^(?:你?好|嗨|hi|hello|谢谢|多谢|再见|早上好|中午好|下午好|晚上好)[!！。,.，?？]*$",
    re.IGNORECASE,
)
_CALCULATION = re.compile(
    r"^(?:(?:请帮我|帮我|请)?(?:计算一下|计算出?|算一下|算出?|求))?"
    r"[0-9０-９+\-*/×÷%^().（）\s]+(?:等于多少|是多少|的结果)?[?？。]*$"
)
_TIME = re.compile(r"(?:现在|当前|今天|明天).{0,12}(?:几点|时间|日期|星期)")
_MEMORY = re.compile(r"(?:记忆|记住|忘记|别记|不要记|删除.*记忆|修改.*记忆|我.*偏好)")
_SETTINGS = re.compile(r"(?:设置|配置).{0,16}(?:模型|Agent|助手|人格|工作区|上下文|技能|MCP)", re.I)
_KNOWLEDGE = re.compile(
    r"(?:知识库|我上传的|上传的(?:资料|文档|文件|附件)|(?:文档|资料|报告)(?:中|里|内)|"
    r"(?:根据|结合|检索|查询)(?:这份|该|我的)?(?:资料|文档|文件|附件|报告))"
)
_DEVELOPMENT = re.compile(
    r"(?:代码|程序|开发|py文件|项目|仓库|git|接口|API|数据库|前端|后端|测试|bug|报错|"
    r"\.py\b|\.tsx?\b|\.jsx?\b|\.md\b|实现.*功能|修改.*文件)",
    re.I,
)
_CURRENT = re.compile(r"(?:最新|今天|当前|实时|现在).{0,18}(?:新闻|天气|价格|版本|动态|热搜)")
_TASK = re.compile(
    r"(?:(?:帮我|请|替我).{0,12})?(?:读取|查看|写入|保存|创建|修改|运行|执行|打开|播放|暂停|搜索|发送|生成|下载|操作)"
)
_AMBIGUOUS = re.compile(r"(?:帮我|请帮我).{0,10}(?:处理|弄|做|搞|看看|检查)(?:一下)?(?:这个|它|问题|任务)?[。！!？?]*$")
_CAPABILITY_QUESTION = re.compile(
    r"^(?:你|助手|雷姆)?(?:现在)?(?:能不能|能否|可不可以|会不会|能|会|可以)"
    r".{0,48}(?:吗|么|呢|？|\?)$",
    re.I,
)


@dataclass(frozen=True)
class IntentResult:
    intent: str
    action: str
    needs_memory: bool
    needs_knowledge: bool
    needs_workspace: bool
    needs_plan: bool
    candidate_tools: tuple[str, ...]
    risk_hint: str
    confidence: float
    source: str

    def to_dict(self) -> dict:
        value = asdict(self)
        value["candidate_tools"] = list(self.candidate_tools)
        return value

    @classmethod
    def from_dict(cls, value: dict) -> "IntentResult":
        return cls(
            intent=str(value.get("intent") or "conversation"),
            action=str(value.get("action") or "respond"),
            needs_memory=bool(value.get("needs_memory", True)),
            needs_knowledge=bool(value.get("needs_knowledge", False)),
            needs_workspace=bool(value.get("needs_workspace", False)),
            needs_plan=bool(value.get("needs_plan", False)),
            candidate_tools=tuple(str(item) for item in value.get("candidate_tools", [])),
            risk_hint=str(value.get("risk_hint") or "low"),
            confidence=float(value.get("confidence", 0.0)),
            source=str(value.get("source") or "persisted"),
        )


def _result(
    intent: str,
    action: str,
    *,
    memory: bool,
    knowledge: bool = False,
    workspace: bool = False,
    plan: bool = False,
    tools: tuple[str, ...] = (),
    risk: str = "low",
    confidence: float = 0.99,
    source: str = "rule",
) -> IntentResult:
    return IntentResult(
        intent, action, memory, knowledge, workspace, plan, tools, risk, confidence, source
    )


def rule_intent(message: str) -> IntentResult | None:
    text = re.sub(r"\s+", "", message).strip()
    if not text:
        return _result("conversation", "respond", memory=False)
    if _GREETING.fullmatch(text):
        return _result("conversation", "respond", memory=False)
    if _CALCULATION.fullmatch(text) and re.search(r"[+\-*/×÷%^]", text):
        return _result(
            "calculation", "calculate", memory=False, tools=("calculate",), confidence=1.0
        )
    if _TIME.search(text):
        return _result(
            "current_information", "get_time", memory=False, tools=("get_time",)
        )
    # “你能不能写前端”是在询问能力，不是要求立刻修改项目。
    # 放在开发关键词之前，避免用户选中规划模式时生成无意义计划。
    if _CAPABILITY_QUESTION.fullmatch(text):
        return _result(
            "conversation",
            "explain_capability",
            memory=True,
            confidence=1.0,
        )
    if _MEMORY.search(text):
        return _result("memory_management", "manage_memory", memory=True)
    if _SETTINGS.search(text):
        return _result("settings_change", "change_settings", memory=False, risk="medium")
    development = bool(_DEVELOPMENT.search(text))
    knowledge = bool(_KNOWLEDGE.search(text) or re.search(r"\.(?:pdf|docx|txt|md)\b", text, re.I))
    if development:
        return _result(
            "software_development",
            "modify_or_analyze_code",
            memory=True,
            knowledge=knowledge,
            workspace=True,
            plan=True,
            tools=(
                "skill_load",
                "code_list_files",
                "code_search",
                "code_read",
                "code_create_file",
                "code_edit",
                "code_git_diff",
                "code_run_check",
            ),
            risk="high",
        )
    if knowledge:
        return _result("knowledge_query", "retrieve_knowledge", memory=True, knowledge=True)
    if _CURRENT.search(text):
        return _result("current_information", "retrieve_current_information", memory=False)
    if _TASK.search(text):
        return _result(
            "task_execution", "execute_task", memory=True, plan=True, risk="high"
        )
    return None


def _parse_model_result(raw: str) -> IntentResult | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        value = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    intent = str(value.get("intent") or "")
    if intent not in INTENTS:
        return None
    try:
        confidence = max(0.0, min(1.0, float(value.get("confidence", 0))))
    except (TypeError, ValueError):
        return None
    return IntentResult(
        intent=intent,
        action=str(value.get("action") or "respond")[:80],
        needs_memory=bool(value.get("needs_memory", True)),
        needs_knowledge=bool(value.get("needs_knowledge", False)),
        needs_workspace=bool(value.get("needs_workspace", False)),
        needs_plan=bool(value.get("needs_plan", False)),
        candidate_tools=tuple(
            str(item)[:100] for item in value.get("candidate_tools", []) if isinstance(item, str)
        )[:20],
        risk_hint=(str(value.get("risk_hint") or "low") if str(value.get("risk_hint") or "low") in {"low", "medium", "high"} else "low"),
        confidence=confidence,
        source="model",
    )


async def route_intent(message: str, provider=None) -> IntentResult:
    matched = rule_intent(message)
    if matched is not None:
        return matched
    if provider is not None and _AMBIGUOUS.search(re.sub(r"\s+", "", message)):
        try:
            raw = await provider.complete(
                [
                    {"role": "system", "content": PROMPT_FILE.read_text(encoding="utf-8")},
                    {"role": "user", "content": json.dumps({"message": message}, ensure_ascii=False)},
                ],
                temperature=0.0,
            )
            classified = _parse_model_result(raw)
            if classified is not None and classified.confidence >= 0.65:
                return classified
        except Exception:
            pass
        return _result(
            "conversation",
            "clarify_or_respond",
            memory=True,
            confidence=0.4,
            source="model_fallback",
        )
    return _result("conversation", "respond", memory=True, confidence=0.8, source="default")


def narrow_allowed_tools(intent: IntentResult, allowed_tools: set[str]) -> set[str]:
    """意图只推荐工具，不再撤销用户已经启用的能力。

    真正的权限边界仍由 Skill/MCP 开关、Executor 白名单、风险审批和参数校验负责；
    candidate_tools 只用于提示模型优先选择，不具有授权或撤权能力。
    """
    return set(allowed_tools)
