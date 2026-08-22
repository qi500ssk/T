# MCP 配置目录

这里保存用户手工添加的 MCP Server 声明，例如传输方式、启动命令、允许工具和风险等级。

- MCP 的实现代码：`mcp_servers/`
- MCP 的用户连接配置：`config/`
- 把 MCP 与 Skill 组合起来统一开关：`plugins/`

密钥只通过环境变量或认证 Header 配置，管理 API 和界面不会回显密钥值。
