"""Developer Tools 的受限工作区文件操作与固定检查命令。"""

from __future__ import annotations

import asyncio
import os
import signal
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import anyio

from infrastructure.config import settings
from core.execution.workspace import current_coding_workspace


MAX_READ_BYTES = 256 * 1024
MAX_READ_LINES = 400
MAX_WRITE_BYTES = 1024 * 1024
MAX_LIST_ENTRIES = 300
MAX_LIST_DEPTH = 5
MAX_SEARCH_FILES = 800
MAX_SEARCH_MATCHES = 120
MAX_SEARCH_FILE_BYTES = 512 * 1024
MAX_PROCESS_OUTPUT = 24_000
EXCLUDED_DIRECTORIES = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    ".next", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
}
SENSITIVE_FILENAMES = {
    ".env", ".npmrc", ".pypirc", "credentials", "credentials.json",
    "id_rsa", "id_ed25519", "known_hosts",
}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".keystore"}
CHECKS = {
    "pytest": ("python", "-m", "pytest", "-q"),
    "python-compile": ("python", "-m", "compileall", "-q", "."),
    "npm-test": ("npm", "run", "test"),
    "npm-lint": ("npm", "run", "lint"),
    "npm-build": ("npm", "run", "build"),
    "npm-typecheck": ("npm", "run", "typecheck"),
}


class CodingToolError(ValueError):
    pass


def _workspace_root() -> Path:
    root = current_coding_workspace()
    if root is None:
        raise CodingToolError("当前对话未选择文件夹，编码工具不可用")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    if lowered in SENSITIVE_FILENAMES or Path(lowered).suffix in SENSITIVE_SUFFIXES:
        return True
    return lowered.startswith(".env.") and lowered != ".env.example"


def _workspace_path(raw_path: str, *, allow_sensitive: bool = False) -> Path:
    raw = str(raw_path or ".").strip() or "."
    relative = Path(raw)
    if relative.is_absolute():
        raise CodingToolError("路径必须是编码工作区内的相对路径")
    if any(part in {"..", ""} for part in relative.parts):
        raise CodingToolError("路径不能逃出编码工作区")
    lowered_parts = {part.lower() for part in relative.parts}
    if lowered_parts & EXCLUDED_DIRECTORIES:
        raise CodingToolError("不允许直接访问依赖、缓存或版本控制内部目录")
    if not allow_sensitive and any(_is_sensitive_name(part) for part in relative.parts):
        raise CodingToolError("默认禁止读取或修改密钥、凭据和环境变量文件")

    root = _workspace_root()
    current = root
    for part in relative.parts:
        if part == ".":
            continue
        current = current / part
        if current.exists() and current.is_symlink():
            raise CodingToolError("不允许访问符号链接")
    resolved = (root / relative).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CodingToolError("路径不能逃出编码工作区") from exc
    return resolved


def _relative(path: Path) -> str:
    value = path.relative_to(_workspace_root()).as_posix()
    return value or "."


def _iter_files(root: Path):
    stack: list[Path] = [root]
    visited = 0
    while stack and visited < MAX_SEARCH_FILES:
        folder = stack.pop()
        try:
            children = sorted(folder.iterdir(), key=lambda item: item.name.lower(), reverse=True)
        except OSError:
            continue
        for child in children:
            if child.is_symlink():
                continue
            if child.is_dir():
                if child.name.lower() not in EXCLUDED_DIRECTORIES:
                    stack.append(child)
                continue
            visited += 1
            if visited > MAX_SEARCH_FILES:
                return
            if not _is_sensitive_name(child.name):
                yield child


def _list_files_sync(raw_path: str) -> str:
    target = _workspace_path(raw_path)
    if not target.exists() or not target.is_dir():
        raise CodingToolError("目录不存在")
    root = _workspace_root()
    rows: list[str] = []
    stack: list[tuple[Path, int]] = [(target, 0)]
    while stack and len(rows) < MAX_LIST_ENTRIES:
        folder, depth = stack.pop()
        try:
            children = sorted(folder.iterdir(), key=lambda item: item.name.lower(), reverse=True)
        except OSError:
            continue
        for child in children:
            if len(rows) >= MAX_LIST_ENTRIES:
                break
            if child.is_symlink() or _is_sensitive_name(child.name):
                continue
            if child.is_dir():
                if child.name.lower() in EXCLUDED_DIRECTORIES:
                    continue
                rows.append(f"{child.relative_to(root).as_posix()}/")
                if depth < MAX_LIST_DEPTH:
                    stack.append((child, depth + 1))
            else:
                rows.append(child.relative_to(root).as_posix())
    rows.sort()
    suffix = "\n[目录结果已截断]" if len(rows) >= MAX_LIST_ENTRIES else ""
    return "\n".join(rows) + suffix if rows else "目录为空"


async def code_list_files(args: dict) -> str:
    return await anyio.to_thread.run_sync(_list_files_sync, args.get("path", "."))


def _read_source(path: Path) -> str:
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise CodingToolError("文件不存在或不是普通文件")
    with path.open("rb") as handle:
        data = handle.read(MAX_READ_BYTES + 1)
    if len(data) > MAX_READ_BYTES:
        raise CodingToolError("文件超过 256KB，请缩小文件或拆分后读取")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CodingToolError("仅支持 UTF-8 文本代码文件") from exc


def _read_code_sync(raw_path: str, start_line: int, end_line: int | None) -> str:
    path = _workspace_path(raw_path)
    content = _read_source(path)
    lines = content.splitlines()
    start = max(1, start_line)
    requested_end = end_line if end_line is not None else start + MAX_READ_LINES - 1
    end = min(len(lines), requested_end, start + MAX_READ_LINES - 1)
    if start > max(1, len(lines)) or requested_end < start:
        raise CodingToolError("行号范围无效")
    body = "\n".join(
        f"{index:>5} | {lines[index - 1]}" for index in range(start, end + 1)
    )
    header = f"{_relative(path)} · lines {start}-{end} / {len(lines)}"
    suffix = "\n[单次最多返回 400 行]" if requested_end > end else ""
    return f"{header}\n{body}{suffix}"


async def code_read(args: dict) -> str:
    return await anyio.to_thread.run_sync(
        _read_code_sync,
        args["path"],
        args.get("start_line", 1),
        args.get("end_line"),
    )


def _search_code_sync(query: str, raw_path: str) -> str:
    needle = query.strip()
    if not needle or len(needle) > 200 or "\n" in needle:
        raise CodingToolError("搜索文本长度必须在 1 到 200 个字符之间")
    target = _workspace_path(raw_path)
    if not target.exists() or not target.is_dir():
        raise CodingToolError("搜索目录不存在")
    lowered = needle.casefold()
    matches: list[str] = []
    for path in _iter_files(target):
        try:
            if path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                continue
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            if lowered in line.casefold():
                compact = line.strip().replace("\t", " ")[:300]
                matches.append(f"{_relative(path)}:{line_number}: {compact}")
                if len(matches) >= MAX_SEARCH_MATCHES:
                    return "\n".join(matches) + "\n[搜索结果已截断]"
    return "\n".join(matches) if matches else "未找到匹配内容"


async def code_search(args: dict) -> str:
    return await anyio.to_thread.run_sync(
        _search_code_sync, args["query"], args.get("path", ".")
    )


def _atomic_write(path: Path, content: str) -> int:
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise CodingToolError("文件内容超过 1MB 限制")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=".coding-", suffix=".tmp", delete=False
    ) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return len(encoded)


def _create_file_sync(raw_path: str, content: str) -> str:
    path = _workspace_path(raw_path)
    if path.exists():
        raise CodingToolError("文件已存在；请使用 code_edit 进行精确修改")
    size = _atomic_write(path, content)
    return f"已创建 {_relative(path)}（{size} 字节）"


async def code_create_file(args: dict) -> str:
    return await anyio.to_thread.run_sync(_create_file_sync, args["path"], args["content"])


def _edit_file_sync(raw_path: str, old_text: str, new_text: str) -> str:
    if not old_text:
        raise CodingToolError("old_text 不能为空")
    path = _workspace_path(raw_path)
    content = _read_source(path)
    occurrences = content.count(old_text)
    if occurrences != 1:
        raise CodingToolError(f"old_text 必须精确匹配一次，当前匹配 {occurrences} 次")
    updated = content.replace(old_text, new_text, 1)
    size = _atomic_write(path, updated)
    return f"已修改 {_relative(path)}（{size} 字节）"


async def code_edit(args: dict) -> str:
    return await anyio.to_thread.run_sync(
        _edit_file_sync, args["path"], args["old_text"], args["new_text"]
    )


def _safe_process_env() -> dict[str, str]:
    allowed = {
        "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
        "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "LANG", "LC_ALL",
    }
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    result.update({"PYTHONIOENCODING": "utf-8", "NO_COLOR": "1"})
    return result


def _run_process(command: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=_safe_process_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise CodingToolError("命令执行超时") from exc
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    if len(output) > MAX_PROCESS_OUTPUT:
        output = output[:MAX_PROCESS_OUTPUT].rstrip() + "\n[命令输出已截断]"
    return completed.returncode, output


def _git_diff_sync() -> str:
    root = _workspace_root()
    git = shutil.which("git")
    if not git:
        raise CodingToolError("系统未安装 Git")
    if not (root / ".git").is_dir():
        raise CodingToolError("编码工作区不是 Git 仓库")
    common = [git, "-c", "core.pager=cat"]
    status_code, status = _run_process(
        common + ["status", "--short", "--untracked-files=normal"], root, 10
    )
    diff_code, diff = _run_process(
        common + ["diff", "--no-ext-diff", "--no-textconv", "--"], root, 10
    )
    if status_code or diff_code:
        raise CodingToolError("Git 无法读取当前改动")
    return f"Git status:\n{status or '工作区干净'}\n\nGit diff:\n{diff or '没有已跟踪文件改动'}"


async def code_git_diff(_: dict) -> str:
    return await anyio.to_thread.run_sync(_git_diff_sync)


def _prepare_check(check: str, raw_path: str) -> tuple[list[str], Path]:
    if check not in CHECKS:
        raise CodingToolError(f"不支持的检查类型：{check}")
    cwd = _workspace_path(raw_path)
    if not cwd.exists() or not cwd.is_dir():
        raise CodingToolError("检查目录不存在")
    command = list(CHECKS[check])
    if command[0] == "python":
        command[0] = sys.executable
    elif command[0] == "npm":
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            raise CodingToolError("系统未安装 npm")
        if not (cwd / "package.json").is_file():
            raise CodingToolError("目标目录没有 package.json")
        command[0] = npm
    return command, cwd


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name == "nt":
            taskkill = shutil.which("taskkill.exe") or shutil.which("taskkill")
            if taskkill:
                killer = await asyncio.create_subprocess_exec(
                    taskkill,
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                await killer.wait()
            else:
                process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        await asyncio.wait_for(process.wait(), timeout=5)
    except (LookupError, OSError, TimeoutError):
        if process.returncode is None:
            process.kill()
            await process.wait()


async def code_run_check(args: dict) -> str:
    command, cwd = _prepare_check(args["check"], args.get("path", "."))
    process_kwargs: dict = {
        "cwd": cwd,
        "env": _safe_process_env(),
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    if os.name == "nt":
        process_kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        process_kwargs["start_new_session"] = True
    process = await asyncio.create_subprocess_exec(*command, **process_kwargs)
    try:
        stdout, stderr = await process.communicate()
    except asyncio.CancelledError:
        await asyncio.shield(_terminate_process_tree(process))
        raise
    output = "\n".join(
        part.decode("utf-8", errors="replace").strip()
        for part in (stdout, stderr)
        if part.strip()
    )
    if len(output) > MAX_PROCESS_OUTPUT:
        output = output[:MAX_PROCESS_OUTPUT].rstrip() + "\n[命令输出已截断]"
    return f"check={args['check']}\nexit_code={process.returncode}\n{output or '命令未输出文本'}"
