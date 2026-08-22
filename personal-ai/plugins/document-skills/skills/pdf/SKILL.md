---
name: pdf
description: 根据用户内容创建支持中文、带清晰标题层级和页码的 PDF。
required_tools:
  - mcp_document-skills-generator_create_pdf
enabled: true
source: local
---
当用户明确要求生成 PDF 文件时使用本 Skill。

先整理标题和正文结构。正文使用 Markdown 风格的标题、段落、项目符号或编号步骤。控制内容密度，避免把未经确认的信息写成事实。

调用 `mcp_document-skills-generator_create_pdf` 后，最终回答必须保留工具返回的 Markdown 下载链接，并简要说明文件包含什么。
