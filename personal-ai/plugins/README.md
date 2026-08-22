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

`Developer Tools` 只声明 Skill，不在插件目录放 Python 实现；受审查的实现位于 `core/execution/coding_tools.py`，插件关闭后工具不会进入请求白名单。
