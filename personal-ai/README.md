# Personal AI

一个面向个人长期使用的本地 AI Agent。项目提供流式对话、分层记忆、知识库检索、工具调用、任务规划和活动调度，并通过权限确认控制写文件、运行命令及 MCP 工具等操作。

## 主要能力

- SSE 流式对话、会话管理和上下文预算控制
- 全局、项目、会话作用域的长期记忆，支持纠正、替换、停用和过期
- PDF、DOCX、TXT、Markdown 知识库与混合检索
- 自主模式与规划模式，支持中断、恢复和执行记录
- 本地工具、Skill、声明式插件和 MCP Server
- 高风险操作审批、工具白名单、超时和审计记录
- 定时或一次性活动任务
- Agent 人格、模型、上下文窗口和编码工作区设置

## 技术栈

| 部分 | 技术 |
|---|---|
| 后端 | Python 3.11+、FastAPI、SQLAlchemy、Alembic |
| 数据库 | PostgreSQL 16、pgvector |
| 前端 | Next.js 16、React 19、TypeScript、Tailwind CSS 4 |
| 检索 | pgvector、BM25、RRF、可配置 Embedding Provider |
| 协议 | HTTP、SSE、MCP |

## 环境要求

- Python 3.11 或更高版本
- [uv](https://docs.astral.sh/uv/)
- Node.js 20 或更高版本
- Docker Desktop 或兼容的 Docker 环境

## 快速开始

### 1. 准备配置

```powershell
cd E:\Pycharm\JQ\personal-ai
Copy-Item .env.example .env
```

已有 `.env` 时不要覆盖。`.env` 包含本机配置和密钥，不会提交到 Git。

默认 Embedding Provider 为本地 BGE 模型。如果本机没有示例路径中的模型，可先在 `.env` 中设置：

```dotenv
EMBEDDING_PROVIDER=mock
```

`mock` 适合界面和流程联调，不适合评估真实检索效果。

### 2. 启动 PostgreSQL

```powershell
docker compose up -d postgres
```

正式开发数据库监听 `localhost:5432`，数据保存在 Docker volume 中。

### 3. 启动后端

```powershell
uv sync
uv run uvicorn apps.api.main:app --port 8787 --reload
```

应用启动时会检查并应用尚未执行的 Alembic 数据库迁移。

### 4. 启动前端

另开一个终端：

```powershell
cd E:\Pycharm\JQ\personal-ai\apps\web
npm install
npm run dev
```

启动完成后访问：

- 前端：<http://localhost:4321>
- 后端：<http://localhost:8787>
- API 文档：<http://localhost:8787/docs>

首次使用时，在前端“设置与技能 → 模型设置”中填写并测试模型配置。

## 常用配置

主要配置位于 `.env`，完整示例见 `.env.example`。

| 配置 | 作用 |
|---|---|
| `DATABASE_URL` | PostgreSQL 连接地址 |
| `LLM_*` | 可选的部署级模型锁定配置 |
| `EMBEDDING_PROVIDER` | `local`、`openai-compatible` 或 `mock` |
| `CONTEXT_MAX_TOKENS` | 上下文装配预算 |
| `MEMORY_*` | 长期记忆提取与召回参数 |
| `RAG_*` | 知识库检索与分块参数 |
| `AGENT_TIMEOUT_SECONDS` | 单次 Agent 运行总超时 |
| `TOOL_TIMEOUT_SECONDS` | 单个工具调用超时 |
| `CORS_ORIGINS` | 允许访问后端的前端地址 |

通常应在前端保存模型配置。只有部署者需要强制锁定模型时，才在 `.env` 中配置完整的 `LLM_PROVIDER`、`LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`。

## 项目结构

```text
personal-ai/
├── apps/
│   ├── api/                 FastAPI 应用、HTTP API 与 SSE 装配
│   └── web/                 Next.js 前端
├── core/
│   ├── automation/          Planner、活动任务和运行状态
│   ├── capabilities/        Skill、插件与 MCP 能力
│   ├── chat/                对话、上下文、记忆、摘要和模型网关
│   ├── execution/           工具执行、审批与安全策略
│   ├── files/               生成文件和安全存储
│   └── rag/                 文档解析、分块、向量化和检索
├── infrastructure/          配置、数据库模型和初始化
├── migrations/              Alembic 数据库迁移
├── prompts/                 系统、记忆、检索和规划提示词
├── skills/                  本地 Skill
├── plugins/                 声明式插件
├── mcp_servers/             内置 MCP Server
├── evaluation/              离线评测脚本
├── tests/                   后端测试
├── data/                    本地运行数据，不提交 Git
└── compose.yaml             PostgreSQL 开发与测试服务
```

后端依赖方向为 `apps/api → core → infrastructure`。前端负责展示状态和提交操作，不负责决定记忆召回、资料引用或工具权限。

## 数据存储

- 会话、消息、运行记录、计划、记忆和知识库元数据：PostgreSQL
- 记忆与文档向量：PostgreSQL + pgvector
- 上传文件、生成文件和运行时设置：`data/`
- 数据库结构版本：`migrations/`

删除本地 `data/` 不会删除 PostgreSQL 中的数据；删除 Docker volume 会删除正式数据库数据，操作前请先备份。

## 测试与检查

启动隔离测试数据库：

```powershell
docker compose up -d postgres-test
uv run pytest -q
```

测试数据库监听 `localhost:5433`，使用 `personal_ai_test`，与正式数据库隔离。

前端检查：

```powershell
cd apps\web
npm run lint
npm run build
```

离线评测：

```powershell
uv run python -m evaluation.rag
uv run python -m evaluation.memory
uv run python -m evaluation.intent
uv run python -m evaluation.planner
```

## 安全说明

- 不要提交 `.env`、API Key、数据库密码或 `data/` 中的运行数据。
- 工具是否需要确认由后端风险等级和审批策略决定，MCP 配置中的风险等级是其中一部分。
- 编码工具只能访问配置的工作区，并拒绝越界路径、敏感文件和符号链接。
- 项目目前定位为本机单用户应用；对公网开放前必须增加认证、访问控制和生产级密钥管理。

## License

当前仓库尚未声明开源许可证。未经许可，请勿将代码视为可自由再分发的软件。
