# Skill 目录

这里只放可独立启停的 Skill 指令包，一项能力一个文件夹：

```text
skills/
└── <skill-id>/
    └── SKILL.md
```

`SKILL.md` frontmatter 中的 `name` 必须等于 `<skill-id>`，并且只能使用小写字母、数字和连字符。中文展示含义应写在 `description`，不要写进 `name`。

从 GitHub 下载到只有 `SKILL.md` 的能力时，将整个能力文件夹放到这里，或在“设置 → 技能”中选择该文件夹导入。

Skill 负责告诉 Agent 何时、如何使用能力；它本身不应承载长期运行的 MCP 服务代码。
