# MCP Server 目录

这里只放项目内置、经过审查的 MCP 服务实现，一项服务一个文件夹：

```text
mcp_servers/
└── <server-id>/
    ├── __init__.py
    └── server.py
```

当前 `document_skills/` 包含文档 MCP 协议入口、隔离 Worker 和格式生成器。插件清单通过 `python -m mcp_servers.document_skills.server` 启动它。

从 GitHub 获得第三方 MCP 时，不要直接合并进 API 代码。先审查来源和启动命令，再在“设置 → MCP 服务器”中配置；只有确定要作为项目内置可信能力时，才整理到本目录。
