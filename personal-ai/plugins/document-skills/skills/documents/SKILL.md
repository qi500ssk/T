---
name: documents
description: 根据用户内容创建排版清晰的 DOCX，并可向已生成的 DOCX 追加内容。
required_tools:
  - mcp_document-skills-generator_create_docx
  - mcp_document-skills-generator_append_docx
enabled: true
source: local
---
当用户明确要求生成 Word 或 DOCX 文件时使用本 Skill。

创建前先确定标题、用途和主要内容。将正文整理成简洁的 Markdown 风格文本：使用 `#` 到 `###` 表示层级标题，使用 `-` 表示项目符号，使用 `1.` 表示顺序步骤。不要编造用户没有提供的事实；信息不足时可使用明确标注的占位文字。

调用 `mcp_document-skills-generator_create_docx` 后，最终回答必须保留工具返回的 Markdown 下载链接。只有用户明确要求修改已经生成的 DOCX 时，才可使用 `append_docx`，并传入该文件的 artifact_id；这是覆盖写入操作，需要用户审批。
