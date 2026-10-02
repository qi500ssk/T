# Personal AI

一个可以下载到本机运行、长期使用的个人 AI Agent。项目提供流式对话、分层记忆、知识库检索、工具调用、任务规划和活动调度，并通过权限确认控制写文件、运行命令及 MCP 工具等操作。

账号和业务数据默认保存在本机，不需要注册云端账号。使用云端模型时，本次回答所需的对话、记忆和资料片段会发送给所配置的模型服务；使用云端 Embedding 时，文档文本也会发送给该服务。完全离线使用需要同时配置本地模型与本地 Embedding。第一次打开页面即可创建本机账号，不需要注册任何云端服务；忘记密码时用创建账号时保存的一次性恢复码重设。

## 主要能力

- SSE 流式对话、会话管理和上下文预算控制
- 全局、项目、会话作用域的长期记忆，支持纠正、替换、停用和过期
- PDF、DOCX、TXT、Markdown 知识库与混合检索
- 每个好友独立的背景与经历：手写记忆、原始资料提取、草稿审核、来源核对
- 设置页选择本地或在线 Embedding；未下载模型时可用关键词检索
- 自主模式与规划模式，支持中断、恢复和执行记录
- 本地工具、Skill、声明式插件和 MCP Server
- 可选联网搜索：在设置页填写 Tavily Key 并开启，由 AI 按问题决定是否搜索或读取网页
- 高风险操作审批、工具白名单、超时和审计记录
- 定时或一次性活动任务
- Agent 人格、模型、上下文窗口和本地文件夹项目

## 技术栈

| 部分 | 技术 |
|---|---|
| 后端 | Python 3.11+、FastAPI、SQLAlchemy、Alembic |
| 数据库 | PostgreSQL + pgvector（保留 SQLite 测试兼容） |
| 前端 | Next.js 16、React 19、TypeScript、Tailwind CSS 4 |
| 检索 | pgvector 余弦相似度、BM25、RRF |
| 协议 | HTTP、SSE、MCP |

## 环境要求

- Python 3.11 或更高版本
- [uv](https://docs.astral.sh/uv/)
- Node.js 20 或更高版本

## 快速开始

### 1. 准备配置

```powershell
cd personal-ai
Copy-Item .env.example .env
```

已有 `.env` 时不要覆盖。`.env` 包含本机配置和密钥，不会提交到 Git。

默认使用轻量多语言 MiniLM。首次启动没有下载模型时，自动使用真实的关键词检索，仍可上传文档和保存记忆。登录后在“设置 → 知识与记忆检索”选择本地模型并点击下载；确认弹窗会显示预计大小和实际保存目录，确认后才开始。已下载的缓存会标注“已下载”，复用缓存时只读取本地文件。下载后本地语义检索不需要 API Key。

也可选择在线 Embedding 或始终使用关键词模式。`mock` 只用于测试，不适合评估检索效果。旧 `.env` 的显式配置仍保留；已有用户可在设置页切换并重建索引。

### 2. 本机数据库

当前开发环境使用本机 PostgreSQL + pgvector。先运行 `docker compose up -d postgres`，再启动后端。
连接地址由 `.env` 的 `DATABASE_URL` 指定；不要覆盖已有连接地址，否则会打开另一个数据库。首次启动自动运行对应的 Alembic 迁移。
SQLite 仍支持显式 `sqlite:///...` 连接，供测试和回退使用。上传文件与运行时配置目录不因切换数据库而改变。

### 3. 启动后端

```powershell
uv sync
uv run uvicorn apps.api.main:app --port 8787 --reload
```

应用启动时会检查并应用尚未执行的 Alembic 数据库迁移。

### 4. 启动前端

另开一个终端：

```powershell
cd personal-ai/apps/web
npm install
npm run dev
```

启动完成后访问：

- 前端：<http://localhost:4321>
- 后端：<http://localhost:8787>
- 业务 API 需要登录；公开 API 文档入口已关闭。

首次使用直接打开 <http://localhost:4321> 创建本机账号，然后在“设置 → 模型设置”中填写并测试模型配置。账号每台安装只有一个，只能在本机创建，不开放注册。

## 常用配置

主要配置位于 `.env`，完整示例见 `.env.example`。

| 配置 | 作用 |
|---|---|
| `DATABASE_URL` | 数据库连接地址，当前使用本机 PostgreSQL + psycopg |
| `LLM_*` | 可选的部署级模型锁定配置 |
| `EMBEDDING_PROVIDER` | 默认 `fastembed`；另有 `keyword`、`openai-compatible`、兼容旧模型的 `local` 和测试用 `mock` |
| `CHARACTER_MEMORY_TOKENS_BUDGET` | 好友背景与经历的上下文预算，默认 1800 token |
| `CONTEXT_MAX_TOKENS` | 上下文装配预算 |
| `MEMORY_*` | 长期记忆提取与召回参数 |
| `RAG_*` | 知识库检索与分块参数 |
| `AGENT_TIMEOUT_SECONDS` | 单次 Agent 运行总超时 |
| `TOOL_TIMEOUT_SECONDS` | 单个工具调用超时 |
| `CORS_ORIGINS` | 允许访问后端的前端地址 |

通常应在前端保存模型配置。只有需要用环境变量统一锁定模型时，才在 `.env` 中配置完整的 `LLM_PROVIDER`、`LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`。

## 好友的背景与经历

在当前好友的记忆页面打开“背景与经历”，可以直接写下它的故事，也可以上传或选择一份文档，为当前好友生成记忆草稿。不需要选择人物来源类型、填写剧情集数或固定时间线；时间描述与主题标签都可留空。

资料提取会逐段调用当前聊天模型，保留原始文件、片段位置和可核对的引用。先编辑、勾选、确认草稿，再加入正式记忆。系统能检查引用是否出现在原文中，但不能自动保证模型的归纳正确，因此需要人工核对。手写内容保存后直接生效。

聊天时只召回当前好友已启用、知情的记忆。“核心记忆”优先装入有限的上下文预算，其他经历按问题相关性检索；与你相处产生的用户记忆单独保留。自动聊天不会直接读取专属资料来绕过未确认、停用或修改后的记忆；需要核对原文时，可在聊天中显式选择该资料。普通知识库资料仍参与自动 RAG 检索。

每次提取对应一个目标好友，资料随后归属该好友；第一版每份资料最多 300 个片段，每片段最多 12 条草稿，单次提取最多 20 分钟。失败前已保存的草稿可以继续审核；重试会跳过已有的相同内容。重启会将未完成的提取标为失败，可手动重新发起。

## 检索模型与切换

“设置 → 知识与记忆检索”提供以下选择，无需修改源代码：

| 模式 / 模型 | 适用情况 |
|---|---|
| 关键词 | 不下载模型、不配置 Key，按字词匹配 |
| 多语言 MiniLM L12（默认，384 维） | 中文及多语言本地语义检索，使用 FastEmbed / ONNX |
| all-MiniLM-L6-v2（384 维） | 主要处理英文资料 |
| bge-small-zh-v1.5（512 维） | 中文模型备选 |
| 已有模型文件夹 | 原地使用已下载的 Sentence Transformers 模型，包括 BGE Small / Large；检查目录并自动识别维度 |
| OpenAI 兼容在线服务 | 在界面配置地址、Key、模型和维度，例如 text-embedding-3-small；仅服务支持时勾选发送 dimensions |

保存时先测试模型，再为文档片段、有效用户记忆和好友经历统一重建向量；保留原文、记忆正文和片段 ID。界面显示进度，期间暂停其他业务请求，避免混用不同维度。普通下载或推理失败会保留旧配置和索引；关键词检索也能处理模型尚未就绪或索引不匹配的文本。运行时设置写入本机设置文件，重启后继续使用。备份时应一并备份数据库、设置文件和上传目录。

下拉框选择的是**向量模型来源**。不使用向量模型时，文档走 BM25；启用任一本地或在线模型后，文档仍同时走 BM25 和向量召回，通过 RRF 合并排序，没有切换为纯向量检索。好友记忆使用关键词、向量相关性与核心记忆优先的组合，和文档排序分别处理。

本地模型缓存位于系统用户数据目录的 `embedding-models` 下，Windows 默认 `%LOCALAPPDATA%/PersonalAI/embedding-models`；设置页显示当前进程的实际目录及具体模型文件夹。使用在线检索时，索引文本和检索问题会发送到所选服务；从资料提取记忆仍需要聊天模型，本地 Embedding 不会代替它。

已有模型可从“使用已有模型文件夹”入口选择检测到的模型，或粘贴完整路径并点击“检查目录”。支持直接输入 ModelScope 模型根目录，只有一个快照时自动定位到 `snapshots/master` 等实际目录；多个快照需明确选择。目录需包含 `config.json`、`model.safetensors`、`tokenizer.json`、`modules.json` 及对应的 Pooling 配置。原地读取，不复制模型、不补下载文件，也不加载自定义 Python 模块。

轻量 FastEmbed / ONNX 不需要 PyTorch；原有 Sentence Transformers 权重需要可选运行组件。使用该格式时运行 `uv sync --group legacy-embedding`，并用 `uv run --group legacy-embedding uvicorn apps.api.main:app --port 8787 --reload` 启动，或直接使用已安装这些组件的虚拟环境。普通 `uv run` 会同步默认依赖，可能移除可选组件；页面检测到缺少组件时会明确提示，不自动安装。

## 账号与登录

- 第一次打开页面时创建本机账号，密码至少 12 个字符；密码使用带随机盐的 scrypt 保存，会话令牌在数据库中只存摘要。
- 登录页可选“记住我”，勾选后 30 天内免登录，否则默认 7 天。具体时长由 `AUTH_SESSION_HOURS` 和 `AUTH_SESSION_REMEMBER_HOURS` 控制。
- “设置 → 账号与安全”可以修改密码或退出全部设备；改密码会撤销其他设备上的会话。
- 创建账号时会生成 8 组一次性恢复码，只显示一次。忘记密码时在登录页选择“忘记密码？用恢复码重设”，输入用户名和其中任意一组即可设置新密码；用过的恢复码随即作废，重设会撤销全部登录会话。
- 恢复码只保存 SHA-256 摘要，数据库里没有明文，也没有其他找回渠道。“设置 → 账号与安全”可以查看剩余组数并重新生成（旧的一批全部作废）。
- 连续登录失败有全局限速，恢复码同样受限速保护。
- 仅在从其他设备（非本机回环地址）访问时，首次设置才要求一次性设置码，内容在首次启动自动生成的 `data/auth-setup-token` 文件中；本机打开页面创建账号不需要它。

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


├── data/                    本地运行数据，不提交 Git
└── compose.yaml             本机 PostgreSQL / pgvector 数据库服务
```

后端依赖方向为 `apps/api → core → infrastructure`。前端负责展示状态和提交操作，不负责决定记忆召回、资料引用或工具权限。

## 数据存储

- 账号、会话、角色记忆、长期记忆及世界书元数据保存在 PostgreSQL；上传文件、生成文件和模型设置仍保存在本机目录。
- 使用单个后端进程。pgvector 按模型与维度筛选后进行精确向量召回；关键词模式以 NULL 表示没有向量。当前未建立跨模型近似向量索引。
- `.env`、数据库备份与运行时设置包含私密数据，不加入版本控制或发行包。
- PostgreSQL 备份使用 `pg_dump -Fc`，并另行备份上传文件、worldbooks 文件夹和运行时设置。恢复前停止后端，优先恢复至新库，再切换连接。
- SQLite 备份仍可使用 `python -m scripts.backup_database <新文件路径>`。

从 SQLite 切回 PostgreSQL（先停止后端；只创建新目标库，不覆盖已有库）：

```powershell
uv run python -m scripts.migrate_sqlite_to_postgres --source data/personal-ai.db --target-env .env.postgresql-backup --database personal_ai_new --activate
```

脚本先创建一致的 SQLite 副本，迁移所有业务表，逐行比对内容和向量，再修改 `.env`；报告与旧配置位于 `data/backups/postgres-switch-*`。原 SQLite 和旧 PostgreSQL 库保留。PostgreSQL 使用 `migrations/versions/`，SQLite 使用 `migrations/sqlite_versions/`。


## 安全说明

- 不要提交 `.env`、API Key、数据库密码或 `data/` 中的运行数据。
- 工具是否需要确认由后端风险等级和审批策略决定，MCP 配置中的风险等级是其中一部分。
- 编码工具只能访问当前对话所属文件夹，并拒绝越界路径、敏感文件和符号链接。
- 每个编码 Run 使用当前对话所属文件夹的独立目录上下文；未选择文件夹时编码工具不可用。
- 登录保护全部业务接口，写请求还要求同源请求标记。这一层面向本机使用，不要在没有 HTTPS 和反向代理加固的情况下把端口暴露到公网。

## License

当前仓库尚未声明开源许可证。未经许可，请勿将代码视为可自由再分发的软件。
