# Core 功能目录

`core/` 按业务功能域组织，不按“一个类一个文件夹”拆分：

```text
core/
├── chat/          基础聊天、模型、上下文、角色、记忆、摘要
├── execution/     Tool 注册与执行、审批、执行 Hook
├── capabilities/  Skill、MCP Client、Plugin、能力快照
├── automation/    Activity 调度、Planner 与 Replan
├── rag/           文档解析、分块、Embedding、检索
└── files/         生成文件 Artifact 的存储与安全定位
```

依赖方向以聊天运行时为装配中心：

```text
chat → automation / capabilities / execution / rag
automation → chat / capabilities
capabilities → execution
rag、files → infrastructure
```

目录边界：

- `chat/` 只处理回答和上下文，不负责插件安装；
- `execution/` 是所有 Tool 的统一安全入口，插件和 Planner 不得绕过；
- `capabilities/` 负责能力发现、启停和快照，不直接生成最终回答；
- `automation/` 负责计划和后台调度，实际执行仍复用聊天与执行链；
- `rag/` 只处理知识资料，不把普通聊天强制变成 RAG；
- `files/` 只管理生成成品，上传知识库仍由 `rag/` 处理。
