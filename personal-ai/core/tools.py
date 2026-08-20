"""P3 本地工具注册表与安全执行边界。"""

from __future__ import annotations

import ast
import asyncio
import math
import operator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

import anyio

from infrastructure.config import settings


MAX_EXPRESSION_CHARS = 200
MAX_AST_DEPTH = 8
MAX_EXPONENT = 12
MAX_ABS_RESULT = 1e100
MAX_FILE_READ_BYTES = 64 * 1024
MAX_FILE_WRITE_BYTES = 1024 * 1024
MAX_TOOL_RESULT_CHARS = 4000


class ToolValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    risk_level: str
    timeout: float
    runner: Callable[[dict], Awaitable[str]]

    async def run(self, args: dict) -> str:
        return await self.runner(args)


@dataclass(frozen=True)
class ToolExecution:
    content: str
    status: str


def _object_schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


async def _get_time(_: dict) -> str:
    now = datetime.now().astimezone()
    return now.isoformat(timespec="seconds")


_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_expression(node: ast.AST, depth: int = 0) -> int | float:
    if depth > MAX_AST_DEPTH:
        raise ToolValidationError("表达式嵌套过深")
    if isinstance(node, ast.Expression):
        return _eval_expression(node.body, depth + 1)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        value = node.value
    elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        value = _UNARY_OPS[type(node.op)](_eval_expression(node.operand, depth + 1))
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        left = _eval_expression(node.left, depth + 1)
        right = _eval_expression(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ToolValidationError("指数过大")
        value = _BINARY_OPS[type(node.op)](left, right)
    else:
        raise ToolValidationError("表达式包含不允许的语法")
    if isinstance(value, complex) or not math.isfinite(float(value)) or abs(value) > MAX_ABS_RESULT:
        raise ToolValidationError("计算结果超出限制")
    return value


async def _calculate(args: dict) -> str:
    expression = args["expression"].strip()
    if not expression or len(expression) > MAX_EXPRESSION_CHARS:
        raise ToolValidationError("表达式长度不合法")
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_expression(tree)
    except (SyntaxError, ZeroDivisionError, OverflowError) as exc:
        raise ToolValidationError("表达式无法计算") from exc
    return str(result)


def _sandbox_path(raw_path: str) -> Path:
    relative = Path(raw_path)
    if not raw_path.strip() or relative.is_absolute():
        raise ToolValidationError("文件路径必须是沙箱内的相对路径")
    root = Path(settings.sandbox_dir).resolve()
    candidate = root / relative
    current = root
    for part in relative.parts:
        if part in {"", ".", ".."}:
            if part == "..":
                raise ToolValidationError("文件路径不能逃出沙箱")
            continue
        current = current / part
        if current.exists() and current.is_symlink():
            raise ToolValidationError("不允许访问符号链接")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolValidationError("文件路径不能逃出沙箱") from exc
    return resolved


def _read_text(path: Path) -> str:
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise ToolValidationError("文件不存在或不是普通文件")
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_READ_BYTES + 1)
    truncated = len(data) > MAX_FILE_READ_BYTES
    data = data[:MAX_FILE_READ_BYTES]
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolValidationError("仅支持 UTF-8 文本文件") from exc
    return content + ("\n[文件内容已截断]" if truncated else "")


async def _read_file(args: dict) -> str:
    return await anyio.to_thread.run_sync(_read_text, _sandbox_path(args["path"]))


def _write_text(path: Path, content: str) -> str:
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_WRITE_BYTES:
        raise ToolValidationError("写入内容超过大小限制")
    if not path.parent.exists() or not path.parent.is_dir() or path.parent.is_symlink():
        raise ToolValidationError("父目录不存在或不安全")
    if path.exists() and (not path.is_file() or path.is_symlink()):
        raise ToolValidationError("目标不是普通文件")
    path.write_bytes(encoded)
    return f"已写入 {len(encoded)} 字节到 {path.name}"


async def _write_file(args: dict) -> str:
    return await anyio.to_thread.run_sync(_write_text, _sandbox_path(args["path"]), args["content"])


def _validate_args(tool: Tool, args: object) -> dict:
    if not isinstance(args, dict):
        raise ToolValidationError("工具参数必须是 JSON 对象")
    schema = tool.input_schema
    properties = schema.get("properties", {})
    unknown = set(args) - set(properties)
    if unknown:
        raise ToolValidationError(f"未知参数：{', '.join(sorted(unknown))}")
    missing = set(schema.get("required", [])) - set(args)
    if missing:
        raise ToolValidationError(f"缺少参数：{', '.join(sorted(missing))}")
    for name, value in args.items():
        expected = properties[name].get("type")
        if expected == "string" and not isinstance(value, str):
            raise ToolValidationError(f"参数 {name} 必须是字符串")
    return args


def prepare_tool(name: str, args: object, allowed_tools: set[str]) -> tuple[Tool, dict]:
    if name not in allowed_tools:
        raise ToolValidationError(f"工具 {name} 不在本次请求白名单中")
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolValidationError(f"未知工具：{name}")
    return tool, _validate_args(tool, args)


async def execute_tool(name: str, args: object, allowed_tools: set[str]) -> ToolExecution:
    try:
        tool, validated = prepare_tool(name, args, allowed_tools)
        async with asyncio.timeout(tool.timeout):
            content = await tool.run(validated)
        if len(content) > MAX_TOOL_RESULT_CHARS:
            content = content[:MAX_TOOL_RESULT_CHARS].rstrip() + "\n[工具结果已截断]"
        return ToolExecution(content=content, status="completed")
    except TimeoutError:
        return ToolExecution(content="工具执行超时", status="timeout")
    except (ToolValidationError, OSError, ValueError) as exc:
        return ToolExecution(content=f"工具错误：{exc}", status="failed")


TOOLS: dict[str, Tool] = {
    "get_time": Tool(
        name="get_time",
        description="获取当前本地日期、时间和时区。",
        input_schema=_object_schema({}, []),
        risk_level="low",
        timeout=settings.tool_timeout_seconds,
        runner=_get_time,
    ),
    "calculate": Tool(
        name="calculate",
        description="安全计算简单数学表达式。",
        input_schema=_object_schema(
            {"expression": {"type": "string", "description": "需要计算的数学表达式"}},
            ["expression"],
        ),
        risk_level="low",
        timeout=settings.tool_timeout_seconds,
        runner=_calculate,
    ),
    "read_file": Tool(
        name="read_file",
        description="读取沙箱内的 UTF-8 文本文件。",
        input_schema=_object_schema(
            {"path": {"type": "string", "description": "沙箱内相对路径"}}, ["path"]
        ),
        risk_level="medium",
        timeout=settings.tool_timeout_seconds,
        runner=_read_file,
    ),
    "write_file": Tool(
        name="write_file",
        description="新建或完整覆盖沙箱内的 UTF-8 文本文件；每次写入都需要用户审批。",
        input_schema=_object_schema(
            {
                "path": {"type": "string", "description": "沙箱内相对路径"},
                "content": {"type": "string", "description": "要写入的完整文本内容"},
            },
            ["path", "content"],
        ),
        risk_level="high",
        timeout=settings.tool_timeout_seconds,
        runner=_write_file,
    ),
}


DEFAULT_TOOL_NAMES = {"get_time", "calculate"}


def tool_schemas(names: set[str]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for name, tool in TOOLS.items()
        if name in names
    ]


def list_tools() -> list[dict]:
    return [
        {"name": tool.name, "description": tool.description, "risk_level": tool.risk_level}
        for tool in TOOLS.values()
    ]
