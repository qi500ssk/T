"""Document Skills 内置 stdio MCP Server。"""

import json
import asyncio
import sys

from mcp.server.fastmcp import FastMCP


server = FastMCP("personal-ai-document-skills", log_level="WARNING")


async def _run_worker(operation: str, arguments: dict) -> str:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcp_servers.document_skills.worker",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    payload = json.dumps(
        {"operation": operation, "arguments": arguments}, ensure_ascii=False
    ).encode("utf-8")
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(payload), 120)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ValueError("文档生成超时") from None
    try:
        response = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        details = stderr.decode("utf-8", errors="replace")[-1000:]
        raise ValueError(f"文档工作进程返回无效结果：{details}") from exc
    if process.returncode != 0 or not response.get("ok"):
        raise ValueError(str(response.get("error") or "文档生成失败"))
    return str(response["result"])


@server.tool()
async def create_docx(title: str, content: str, filename: str = "document.docx") -> str:
    """Create a polished DOCX from a title and Markdown-like content."""
    return await _run_worker("create_docx", {"title": title, "content": content, "filename": filename})


@server.tool()
async def append_docx(artifact_id: str, content: str) -> str:
    """Append Markdown-like content to an existing generated DOCX artifact."""
    return await _run_worker("append_docx", {"artifact_id": artifact_id, "content": content})


@server.tool()
async def create_pdf(title: str, content: str, filename: str = "document.pdf") -> str:
    """Create a polished PDF from a title and Markdown-like content."""
    return await _run_worker("create_pdf", {"title": title, "content": content, "filename": filename})


@server.tool()
async def create_pptx(title: str, slides_json: str, filename: str = "presentation.pptx") -> str:
    """Create a 16:9 presentation. slides_json is a JSON array of title/bullets objects."""
    slides = json.loads(slides_json)
    return await _run_worker("create_pptx", {"title": title, "slides": slides, "filename": filename})


@server.tool()
async def create_xlsx(title: str, sheets_json: str, filename: str = "workbook.xlsx") -> str:
    """Create an XLSX workbook. sheets_json is a JSON array of name/rows objects."""
    sheets = json.loads(sheets_json)
    return await _run_worker("create_xlsx", {"title": title, "sheets": sheets, "filename": filename})


if __name__ == "__main__":
    server.run(transport="stdio")
