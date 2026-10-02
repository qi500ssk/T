# Personal AI

一个通过 Docker 在本机运行、长期使用的个人 AI Agent。项目提供流式对话、分层记忆、知识库检索、工具调用、任务规划和活动调度，并通过权限确认控制写文件、运行命令及 MCP 工具等操作。

业务数据保存在本机 PostgreSQL 和文件目录中。打开页面即可使用，无需创建账号或登录。使用云端模型时，对话、记忆和资料片段会发送给所配置的服务；完全离线使用需要同时配置本地聊天模型与本地 Embedding。

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
| 后端 | Python 3.11+、FastAPI、SQLAlchemy |
| 数据库 | PostgreSQL + pgvector |
| 前端 | Next.js 16、React 19、TypeScript、Tailwind CSS 4 |
| 检索 | pgvector 余弦相似度、BM25、RRF |
| 协议 | HTTP、SSE、MCP |

## Docker 一键部署

安装并启动 Docker Desktop（Windows 使用 Linux 容器），在 `personal-ai` 目录执行：

```powershell
docker compose up -d --build --wait
```

访问 <http://localhost:4321> 即可使用，无需账号。首次构建需要联网下载镜像和依赖；之后在“设置 → 模型设置”配置聊天模型。前端、后端和 PostgreSQL 会按健康状态依次启动，后端启动时直接创建当前所需表结构。只向本机开放前端 4321 和数据库 5432，后端仅供容器内部访问。

```powershell
docker compose ps                # 查看状态
docker compose logs -f api web   # 查看日志
docker compose stop             # 停止，保留数据
docker compose up -d --build --wait  # 更新并启动
```

数据库、上传资料、模型缓存、运行时设置、MCP 配置、插件与技能都使用持久化卷。保留现有 `personal_ai_postgres` 卷；不要用 `docker compose down -v` 停止日常服务，它会删除数据卷。首次启动新容器不会自动导入原来宿主机的上传文件和设置。

Docker 配置不把本机 `.env` 或密钥打入镜像，也不读取其中宿主机专用的文件路径。可在已有 `.env` 中加入这些 Docker 配置（没有 `.env` 也可直接启动）：

```dotenv
POSTGRES_DB=personal_ai
POSTGRES_PASSWORD=personal_ai_local
WORKSPACE_DIR=./data/workspace
# LEGACY_EMBEDDING=true
```

已有数据库卷的密码和数据库名须与原安装一致；改变这些变量不会更改现有数据库密码，也不会在已有卷内自动新建数据库。当前本地开发的 `DATABASE_URL` 不会被 Docker 覆盖；若要使用其中的已有库，把 `POSTGRES_DB` 设为该连接地址最后的数据库名。

工作区默认挂载宿主机 `data/workspace` 到容器 `/workspace`。Windows 可设置 `WORKSPACE_DIR=E:/你的项目目录`；创建项目时用页面目录浏览选择 `/workspace` 内的文件夹。Windows 原生目录选择器仅用于直接在 Windows 启动后端。文件夹之外的宿主机文件需明确增加挂载，容器不会自动访问电脑上的全部目录。

连接宿主机上的聊天模型、Embedding 或 HTTP MCP 时，地址中的 `localhost` 应改用 `host.docker.internal`；宿主机服务还需要允许 Docker 网络访问。stdio MCP 在后端容器中运行，镜像内有 Python、Node.js/npm 和 Git；自定义 MCP 所需的浏览器或其他程序需要自行提供。已有 Sentence Transformers 格式模型需要取消 `LEGACY_EMBEDDING=true` 的注释并重新构建，且模型目录须放在挂载目录中；默认 FastEmbed 无需这些可选组件。

## 本地开发

需要 Python 3.11+、uv、Node.js 20+ 和 Docker。已有 `.env` 不要覆盖；新环境可复制 `.env.example`。

```powershell
docker compose up -d postgres
uv sync
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8787 --reload
```

另开终端：

```powershell
cd apps/web
npm ci
npm run dev
```

数据库仅支持 PostgreSQL + pgvector，通过 `DATABASE_URL` 指定。前端仍使用 <http://localhost:4321>；运行时设置和文件默认保存在系统用户数据目录。

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
├── prompts/                 系统、记忆、检索和规划提示词
├── skills/                  本地 Skill
├── plugins/                 声明式插件
├── mcp_servers/             内置 MCP Server
├── data/                    本地运行数据，不提交 Git
└── compose.yaml             前端、后端与 PostgreSQL 一键部署
```

后端依赖方向为 `apps/api → core → infrastructure`。前端负责展示状态和提交操作，不负责决定记忆召回、资料引用或工具权限。

## 数据存储

- 会话、角色记忆、长期记忆及世界书元数据保存在 PostgreSQL；上传文件、生成文件和模型设置仍保存在本机目录。
- 使用单个后端进程。pgvector 按模型与维度筛选后进行精确向量召回；关键词模式以 NULL 表示没有向量。当前未建立跨模型近似向量索引。
- `.env`、数据库备份与运行时设置包含私密数据，不加入版本控制或发行包。
- PostgreSQL 备份使用 `pg_dump -Fc`，并另行备份上传文件、worldbooks 文件夹和运行时设置。恢复前停止后端，优先恢复至新库，再切换连接。

## 安全说明

- 不要提交 `.env`、API Key、数据库密码或 `data/` 中的运行数据。
- 工具是否需要确认由后端风险等级和审批策略决定，MCP 配置中的风险等级是其中一部分。
- 编码工具只能访问当前对话所属文件夹，并拒绝越界路径、敏感文件和符号链接。
- 每个编码 Run 使用当前对话所属文件夹的独立目录上下文；未选择文件夹时编码工具不可用。
- 当前没有账号和登录，仅面向本机使用；Docker 端口绑定回环地址，写请求仍要求同源请求标记。

## License

当前仓库尚未声明开源许可证。未经许可，请勿将代码视为可自由再分发的软件。
