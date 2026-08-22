---
name: presentations
description: 根据主题和逐页要点创建简洁的 16:9 PPTX 演示文稿。
required_tools:
  - mcp_document-skills-generator_create_pptx
enabled: true
source: local
---
当用户明确要求生成 PPT、PPTX 或演示文稿时使用本 Skill。

先把内容组织成有顺序的页面，每页必须有简短标题，正文使用不超过 6 个精炼要点。默认控制在 3 到 10 页；用户指定页数时遵循用户要求，但不得超过工具限制。不要把制作过程、提示词或内部规划写进幻灯片。

调用 `mcp_document-skills-generator_create_pptx`，其中 `slides_json` 是 `{title, bullets}` 对象数组序列化后的 JSON 字符串。完成后在最终回答中保留工具返回的 Markdown 下载链接。
