---
name: spreadsheets
description: 根据表头和结构化数据创建格式清晰、保留数据类型的 XLSX 工作簿。
required_tools:
  - mcp_document-skills-generator_create_xlsx
enabled: true
source: local
---
当用户明确要求生成 Excel、XLSX 或电子表格时使用本 Skill。

先确认每个工作表的名称、表头和数据行。传给工具的 `sheets_json` 是 `{name, rows}` 对象数组序列化后的 JSON 字符串，`rows` 必须是二维数组。数字、布尔值和空值应保持原始类型，不要全部转换为文本；需要公式时以 `=` 开头并引用单元格。

调用 `mcp_document-skills-generator_create_xlsx` 后，在最终回答中保留工具返回的 Markdown 下载链接，并说明包含哪些工作表。
