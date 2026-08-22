"""一次性文档生成工作进程；通过 stdin/stdout JSON 与 MCP Server 通信。"""

from __future__ import annotations

import json
import sys

from mcp_servers.document_skills.generation import (
    append_docx,
    create_docx,
    create_pdf,
    create_pptx,
    create_xlsx,
)


HANDLERS = {
    "create_docx": create_docx,
    "append_docx": append_docx,
    "create_pdf": create_pdf,
    "create_pptx": create_pptx,
    "create_xlsx": create_xlsx,
}


def main() -> int:
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        operation = str(request.get("operation", ""))
        arguments = request.get("arguments", {})
        if operation not in HANDLERS or not isinstance(arguments, dict):
            raise ValueError("文档操作无效")
        result = HANDLERS[operation](**arguments)
        response = {"ok": True, "result": result}
    except Exception as exc:
        response = {"ok": False, "error": str(exc)}
    sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
