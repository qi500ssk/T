# Plugin 目录

这里只放插件清单及插件贡献的 Skill，一项插件一个文件夹：

```text
plugins/
└── <plugin-id>/
    ├── plugin.yaml
    └── skills/
        └── <skill-id>/SKILL.md
```

插件负责把多个 Skill 和 MCP 配置组合成一个可统一开关的能力包。导入的新插件默认关闭。

为了避免第三方代码进入 API 主进程，插件文件夹不允许放 `.py`、`.js`、`.exe` 等可执行文件。可信的项目内置 MCP 实现放在 `mcp_servers/`。

插件内每个 Skill 同样遵循标准命名：文件夹 `skills/pdf/` 对应 `SKILL.md` 中的 `name: pdf`，不能写成 `name: PDF 文档`。

当前示例：

- `document-skills/`：通过隔离 MCP 提供文档生成；
- `developer-tools/`：通过项目内置的受限工具提供简单编码能力，默认工作区为 `data/coding-workspace`。
- `web-search/`：通过 Tavily MCP 提供联网搜索和网页读取；先在插件页配置 Tavily API Key，再启用插件。

`Developer Tools` 只声明 Skill，不在插件目录放 Python 实现；受审查的实现位于 `core/execution/coding_tools.py`，插件关闭后工具不会进入请求白名单。

需要凭据的声明式插件可以在 `plugin.yaml` 声明私密设置，并映射到 MCP 子进程环境变量：

```yaml
settings:
  - key: api_key
    label: API Key
    type: secret
    required: true
mcp_servers:
  service:
    transport: stdio
    command: npx
    args: [-y, example-mcp@latest]
    env_from_settings:
      SERVICE_API_KEY: api_key
```

设置值保存在 Git 忽略的本地运行时文件中。插件列表只返回 `configured: true/false`，不会返回原值；必填设置未配置时插件不能启用。
