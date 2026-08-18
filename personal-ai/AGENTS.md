# AGENTS.md — Personal AI Agent

> 工作区指令文件：本项目的架构边界、开发原则与常用命令。开发前请先读本节。

## 项目概览

Chat-first Personal AI Agent（长期个人 AI 助手）。当前已完成 **P2 阶段：理解资料**，交付安全文件入库、混合检索、引用与知识库界面闭环。

- 后端：FastAPI（8787）+ SQLite + SQLAlchemy，SSE 流式聊天
- 前端：Next.js 16 + React 19 + TypeScript + Tailwind v4（4321）
- 架构依据：`E:\Pycharm\JQ\personal_ai_agent_architecture_merged.md`（合并版架构文档）
- 阶段报告：`E:\Pycharm\JQ\baogao\P2.md`

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
├── core/              # 核心业务（扁平模块，P0 不拆子目录）
│   ├── gateway.py     # Model Gateway：openai-compatible / mock 双 provider
│   ├── character.py   # Character 加载 + System Prompt 渲染（core/character.yaml）
│   ├── context.py     # Context Engine：摘要/记忆注入 + token 预算裁剪
│   ├── agent.py       # Agent Runtime：Agent Run 生命周期 + SSE 事件
│   ├── memory.py      # 长期记忆提取、去重、召回
│   ├── summary.py     # 会话增量摘要
│   ├── embedding.py   # 独立 Embedding Gateway
│   └── rag/           # 解析、分块、入库、混合检索
├── infrastructure/    # config.py（.env 配置）、database.py（SQLAlchemy 模型）
├── prompts/system/    # System Prompt 模板（与业务代码解耦）
├── tests/             # pytest（conftest 使用临时库 + mock provider）
└── data/              # 运行时生成的 SQLite
```

## 关键约束（改代码前必读）

1. **LLM 调用必须走 `core/gateway.py`**，业务代码禁止直接调用模型 SDK；新增 provider 在此文件实现。
2. **禁止 `messages = all_history`**：上下文必须经 `core/context.py` 的 build_context（token 预算裁剪）。
3. **前端不做决策**：调哪个 Tool / 读哪条 Memory / 执行哪个 Skill 都由后端控制，前端只渲染后端下发的事件。
4. **SSE 事件协议固定**：`run.started / message.delta / message.completed / run.completed / run.failed`，事件结构为 `event: <type>` + `data: <json>`；新增事件类型不得破坏前端解析。
5. **Character 与 Prompt 与代码解耦**：身份人格改 `core/character.yaml`，话术改 `prompts/system/main.md`，不改代码。
6. **端口约定**：后端 8787、前端 4321。改端口必须同步 4 处：`.env`（API_PORT、CORS_ORIGINS）、`apps/web/package.json`（-p）、`apps/web/.env.local`（NEXT_PUBLIC_API_URL）、README.md。
7. **配置**：`.env`（模型/预算/超时，模板见 `.env.example`）；`.env` 不入库。
8. **数据库模型集中在 `infrastructure/database.py`**（Conversation / Message / AgentRun / Memory / Document / DocumentChunk），新增模型放这里。
9. **RAG 引用由后端决定**：只有实际装入 Context 的 chunk 才能进入 `rag.retrieved` 和消息 citations；前端不得自行构造来源。
10. **文件路径不可使用原文件名**：上传只用 UUID 落盘，读取必须通过 document_id 查库并验证路径仍在 `FILE_STORAGE_DIR` 内。
11. **中文消息**：前后端均 UTF-8；控制台乱码是 GBK 显示问题，不代表数据错误。

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
| P3 开始做事 | 未开始 | Skill、Tool Calling、权限审批、Observability |
| P4 连接外部 | 未开始 | MCP、Web Search、Browser |
| P5 主动工作 | 未开始 | Activity、Scheduler、Job Queue、Worker |
| P6 高级 Agent | 未开始 | Planner、自主活动、插件注册表 |

下一阶段是 P3：在现有受控 Context/RAG 边界上增加 Skill、Tool Calling、权限审批与可观测性。
