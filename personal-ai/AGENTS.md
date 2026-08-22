# AGENTS.md — Personal AI Agent

> 工作区指令文件：本项目的架构边界、开发原则与常用命令。开发前请先读本节。

## 项目概览

Chat-first Personal AI Agent（长期个人 AI 助手）。当前已完成 **P12 阶段：个性化基础设置**，支持本地持久化的 Agent 人格、模型配置和编码工作区选择。

- 后端：FastAPI（8787）+ SQLite + SQLAlchemy，SSE 流式聊天
- 前端：Next.js 16 + React 19 + TypeScript + Tailwind v4（4321）
- 架构依据：`E:\Pycharm\JQ\personal_ai_agent_architecture_merged.md`（合并版架构文档）
- 最新阶段报告：`E:\Pycharm\JQ\personal-ai\docs\P12.md`

## 开发原则（最高优先级）

- **简单 > 复杂；可运行 > 完美；清晰 > 抽象；当前需求 > 未来需求；少依赖 > 多依赖**
- 一个功能能用 30 行解决，不要写 200 行
- 不创建没有实际用途的 BaseClass / Factory / Manager / Service
- 不为了"未来可能用到"提前增加依赖或抽象
- 模块职责单一，避免把大量逻辑写进一个文件
- 删除无用代码、重复代码和不必要的抽象

## 架构与目录（依赖方向：apps/api → core → infrastructure）

```text
personal-ai/
├── apps/api/          # FastAPI：main.py（装配）、chat.py（SSE）、documents.py（知识库 API）
├── apps/web/          # Next.js：app/page.tsx（布局）、components/（Sidebar、ChatView）、lib/api.ts（API+SSE 解析）
├── core/              # 核心业务，按功能域分组
│   ├── chat/          # Agent、Gateway、Context、Character、Memory、Summary
│   ├── execution/     # Tool、Executor、审批和前后置 Hook
│   ├── capabilities/  # Skill、MCP Client/Manager、Plugin、能力快照
│   ├── automation/    # Activity、Planner 和 Replan
│   ├── rag/           # 解析、分块、Embedding、入库、混合检索
│   └── files/         # Artifact UUID 存储、元数据和安全定位
├── infrastructure/    # config.py（.env 配置）、database.py（SQLAlchemy 模型）
├── mcp_servers/       # 内置信任的 MCP 实现；插件目录不放可执行 Python
├── prompts/system/    # System Prompt 模板（与业务代码解耦）
├── tests/             # pytest（conftest 使用临时库 + mock provider）
└── data/              # 运行时生成的 SQLite
```

## 关键约束（改代码前必读）

1. **LLM 调用必须走 `core/chat/gateway.py`**，业务代码禁止直接调用模型 SDK；新增 provider 在此文件实现。
2. **禁止 `messages = all_history`**：上下文必须经 `core/chat/context.py` 的 build_context（token 预算裁剪）。
3. **前端不做决策**：调哪个 Tool / 读哪条 Memory / 执行哪个 Skill 都由后端控制，前端只渲染后端下发的事件。
4. **SSE 事件协议固定**：`run.started / message.delta / message.completed / run.completed / run.failed`，事件结构为 `event: <type>` + `data: <json>`；新增事件类型不得破坏前端解析。
5. **Character 与 Prompt 与代码解耦**：身份人格改 `core/chat/character.yaml`，话术改 `prompts/system/main.md`，不改代码。
6. **端口约定**：后端 8787、前端 4321。改端口必须同步 4 处：`.env`（API_PORT、CORS_ORIGINS）、`apps/web/package.json`（-p）、`apps/web/.env.local`（NEXT_PUBLIC_API_URL）、README.md。
7. **配置**：`.env`（模型/预算/超时，模板见 `.env.example`）；`.env` 不入库。
8. **数据库模型集中在 `infrastructure/database.py`**（包括 Plan / PlanStep），新增模型放这里。
9. **RAG 引用由后端决定**：只有实际装入 Context 的 chunk 才能进入 `rag.retrieved` 和消息 citations；前端不得自行构造来源。
10. **文件路径不可使用原文件名**：上传只用 UUID 落盘，读取必须通过 document_id 查库并验证路径仍在 `FILE_STORAGE_DIR` 内。
11. **中文消息**：前后端均 UTF-8；控制台乱码是 GBK 显示问题，不代表数据错误。
12. **Planner 不能执行或授权**：Plan 只保存语义步骤和工具提示；实际调用必须经过共享 Executor、请求级白名单和既有审批。
13. **默认兼容**：Chat 与 Activity 的 `execution_mode` 默认必须是 `direct`；禁止增加隐式 auto planning。
14. **有限执行**：planned Run 必须共享总超时、工具次数和观察预算；Replan 只能在 blocked 后触发且次数受配置限制。
15. **Skill 渐进加载**：初始 Prompt 只允许 Skill ID、名称和描述；完整正文必须通过本次 Run 绑定的 `skill_load` 获取。
16. **能力可解释**：新 Agent Run 必须持久化 capability_version 和 capability_snapshot；不得保存完整 Skill 正文。
17. **Tool Hook 安全**：前置策略异常必须 fail-closed；第三方策略不得绕过白名单、审批、超时和 ToolRun 记录。
18. **插件不执行任意代码**：本地插件只允许声明式 Skill/MCP 内容；新安装默认关闭，可执行文件必须拒绝。
19. **MCP 密钥不回显**：API 只返回环境变量/Header 键名；stdio 子进程不得继承无关 API Key。
20. **生成文件隔离**：Artifact 必须使用 UUID 目录、受限后缀和大小上限；下载时重新验证路径，不得直接暴露用户提供的本地路径。
21. **文档能力可撤销**：Document Skills 默认关闭；关闭插件后必须同时撤销其 Skill 和 MCP Tool，不得把生成器硬编码进基础聊天能力。
22. **编码工作区隔离**：所有编码路径必须位于 `CODING_WORKSPACE_DIR`；拒绝越界、符号链接、敏感文件和依赖目录。
23. **编码写入需审批**：创建、精确修改和运行检查均为 high 风险；不得绕过统一 Executor、请求白名单、超时与 ToolRun 审计。
24. **不提供任意执行**：Developer Tools 不得加入任意 Shell、依赖安装、删除/移动文件或 Git commit/push/reset；新命令只能作为固定参数的预定义检查评审后加入。
25. **运行时设置不入库**：用户模型 Key、人格和工作区保存在 `RUNTIME_SETTINGS_FILE`；API 不得回显 Key，仓库只保留无密钥默认模板。
26. **自定义 Prompt 不授权**：用户人格提示词可以影响语言和行为偏好，但不得绕过 Skill 白名单、工具审批、MCP 风险与执行超时。
27. **模型切换保护运行任务**：存在 running AgentRun 时拒绝热切换；新 Provider 成功建立后才替换旧 Provider，并同步重启单 Activity Worker。
28. **目录浏览仅限本机部署**：文件夹选择 API 只列目录、不读文件；服务对公网开放前必须增加认证和目录根限制。

## 常用命令

```powershell
# 后端（在 personal-ai/ 下）
uv sync                                    # 安装依赖
uv run pytest                              # 跑测试（改动后端后必须全绿）
uv run uvicorn apps.api.main:app --port 8787 --reload

# 前端（在 apps/web/ 下）
npm install
npm run dev                                # http://localhost:4321
npm run build                              # 改动前端后必须构建通过
```

## 阶段路线与当前状态

| 阶段 | 状态 | 内容 |
|---|---|---|
| P0 聊天 MVP | ✅ 完成 | 流式聊天、会话管理、Agent Run、Context Engine、Model Gateway、Character |
| P1 认识用户 | ✅ 完成 | 长时记忆自动提取、会话摘要、记忆召回、Memory UI |
| P2 理解资料 | ✅ 完成 | 安全文件上传、PDF/DOCX/TXT/MD、BGE、Vector+BM25+RRF、引用、Knowledge UI、评测 |
| P3 开始做事 | ✅ 完成 | Skill、Tool Calling、权限审批、Observability |
| P4 连接外部 | ✅ 完成 | stdio MCP Client、Tool 适配、Demo Server、故障隔离 |
| P5 主动工作 | ✅ 完成 | Activity、持久化调度、单进程 Worker、重启恢复 |
| P6 高级 Agent | ✅ 完成 | 受限 Planner、共享 Executor、有界 Replan、Plan UI/API、Capability Registry |
| P7 本地技能管理 | ✅ 完成 | Skill 动态扫描、持久化开关、刷新 API、内置技能和独立设置页 |
| P8 渐进式能力运行时 | ✅ 完成 | Skill 按需加载、Provider Registry、Run 能力版本、Tool 安全 Hook |
| P9 MCP 与插件管理 | ✅ 完成 | stdio/HTTP MCP Manager、热启停、普通文件夹声明式插件、三页设置中心 |
| P10 Document Skills | ✅ 完成 | 默认关闭的文档插件、四类 Skill、隔离生成 Worker、Artifact 下载 |
| P11 简单编码能力 | ✅ 完成 | 默认关闭的 Developer Tools、工作区隔离、精确编辑、Git diff、预定义检查 |
| P12 个性化基础设置 | ✅ 完成 | Agent 人格与自定义 Prompt、模型脱敏配置/热切换、本机工作区选择 |

P12 后续可做多 Agent 预设、模型高级参数、人格导入导出、变更预览和 GitHub 能力包导入向导；进程内任意代码插件和分布式 Worker 均不提前引入。
