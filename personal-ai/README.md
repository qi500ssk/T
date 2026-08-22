# Personal AI Agent（P12：个性化基础设置）

Chat-first Personal AI：支持流式聊天、长期记忆、个人资料知识库、经过权限控制的本地与 MCP 工具执行、持久化 Activity、显式 Planner，以及可动态刷新和开关的 Skill、MCP Server 与声明式插件。

最新交付说明见 [P12 阶段开发报告](docs/P12.md)，简单编码能力见 [P11 阶段开发报告](docs/P11.md)。

## 已完成功能

- FastAPI + SSE 流式聊天，会话、消息与 Agent Run 持久化
- 会话增量摘要、长期记忆提取/召回/启停和敏感信息过滤
- PDF、DOCX、TXT、Markdown 安全上传与 UUID 原文件存储
- 文档解析、结构化分块、tokenizer/字符/页数/解压大小/超时限制
- 本地 `bge-small-zh-v1.5`、OpenAI-compatible 和 Mock Embedding Provider
- 向量相似度 + BM25 + RRF 混合检索
- 轻量查询门控跳过计算、问候和当前信息等非资料问题，仅展示回答实际使用的引用
- Memory、RAG、Summary、Recent Messages 独立预算与总 token 硬上限
- `rag.retrieved` SSE 事件、引用白名单、消息引用持久化
- 工作区提供对话、记忆、知识库和活动；设置工作区独立管理技能、MCP 服务器和插件
- 固定 20 条中文检索评测，输出 Recall@1/3/5、MRR、章节与关键词命中率
- OpenAI 兼容 Tool Calling，多回合执行后由模型基于工具结果回答
- `get_time`、安全计算、沙箱文件读取和审批后写入
- `skills/*/SKILL.md` 动态扫描、格式/依赖状态、持久化开关与请求级工具白名单
- 目录加入 Skill 后无需修改 Python 业务代码，点击刷新即可出现在设置页
- 设置页可直接导入普通 Skill 文件夹、新建 Skill，并将本地 Skill 可恢复地移入回收目录
- System Prompt 只注入 Skill 轻量目录，完整正文通过 `skill_load` 按当前 Run 快照渐进加载
- Skill Provider Registry 支持优先级、可撤销注册、失败回退和稳定目录版本
- 每个 Agent Run 持久化能力版本、Skill 摘要哈希和最终工具白名单
- Tool 前置安全 Hook 采用 fail-closed，后置 Hook 可扩展审计和结果规范化
- 6 个普通用户内置 Skill：时间、计算、笔记、润色、总结和翻译
- 工具状态、写入审批卡片、`tool_runs` 执行记录和结构化日志
- 官方 MCP SDK stdio / Streamable HTTP 客户端，支持连接测试、状态、配置持久化和热启停
- 声明式插件普通文件夹可组合多个 Skill 与 MCP Server，默认关闭并拒绝可执行代码
- `mcp_demo_echo` 和需要审批的 `mcp_demo_random_number` 全链路示例
- 默认关闭的 `Document Skills` 插件，按需提供 DOCX、PDF、PPTX 和 XLSX 生成能力
- 文档 MCP 使用一次性 Worker 隔离生成库，关闭插件后立即撤销 4 个 Skill 和 5 个工具
- UUID Artifact 安全存储、大小限制、下载 API 与聊天工具卡片下载入口
- 默认关闭的 `Developer Tools` 插件，在独立编码工作区中提供读取、搜索、精确编辑、Git diff 和预定义检查
- 编码写入与检查需要审批；拒绝越界、敏感文件、符号链接、任意 Shell、依赖安装和 Git 修改操作
- 设置页可编辑 Agent 名称、角色、语言、性格维度和自定义 System Prompt，并立即应用到 Chat 与 Activity
- 支持 Mock、DeepSeek、Ollama 和其他 OpenAI 兼容模型的脱敏配置、连接测试与安全热切换
- 内置本机文件夹浏览器选择编码工作区，路径热更新且不自动扩大 Developer Tools 权限
- 一次性和固定分钟间隔 Activity，支持暂停、恢复、立即运行和删除
- FastAPI lifespan 内单协程 Worker，计划、状态、结果和重启恢复均持久化
- Activity 复用现有 Agent / Skill / Tool / MCP 链路，后台高风险工具直接拒绝
- 每个 Activity 使用专属会话保存历史结果，可从活动页面直接跳转查看
- Chat 与 Activity 可显式选择 `direct` 或 `planned`，默认保持 `direct`
- 严格 JSON Planner、2..6 个顺序步骤、一次有界 Replan 和无工具最终汇总
- Plan / PlanStep 状态、版本、结果与错误持久化，并通过 SSE 实时展示
- direct / planned 共用 Executor、工具白名单、审批、ToolRun 与总工具预算
- 只读 Capability Registry 汇总当前 Native Tool、Skill 与 MCP 能力
- 同会话单 running Run 数据库约束、安全会话删除和 P5 旧库兼容迁移

## 快速开始

```powershell
cd E:\Pycharm\JQ\personal-ai
uv sync
Copy-Item .env.example .env   # 首次运行；已有 .env 不要覆盖
uv run uvicorn apps.api.main:app --port 8787 --reload
```

另开终端：

```powershell
cd E:\Pycharm\JQ\personal-ai\apps\web
npm install
npm run dev
```

- 前端：`http://localhost:4321`
- 后端：`http://localhost:8787`
- API 文档：`http://localhost:8787/docs`

默认使用本地 BGE 路径。若只需轻量联调，可在 `.env` 设置 `EMBEDDING_PROVIDER=mock`。通常请在应用的“模型设置”中保存模型配置与凭据；如果 `.env` 中提供了一套完整的 `LLM_*` 配置，系统会进入环境模型锁定模式，并强制覆盖所有前端模型选择。

## 目录

```text
personal-ai/
├── apps/api/             FastAPI 装配、聊天 SSE、知识库、Activity、Plan、能力管理 API
├── apps/web/             Next.js UI（工作区与 Skill/MCP/Plugin 设置中心）
├── core/
│   ├── chat/             Agent、Model Gateway、Context、角色、记忆和摘要
│   ├── execution/        Tool 注册、统一执行循环、审批、安全 Hook 与受限编码工具
│   ├── capabilities/     Skill、MCP Client、Plugin 与能力快照
│   ├── automation/       Activity、Planner、Replan 与状态操作
│   ├── rag/              解析、分块、Embedding、入库和混合检索
│   └── files/            Artifact UUID 存储、元数据与安全下载定位
├── skills/               内置与用户加入的本地 Skill 指令包
├── plugins/              已安装的声明式插件普通文件夹
├── mcp_servers/           内置可信 MCP 实现（与声明式插件清单分离）
├── config/               MCP Server 配置
├── scripts/              开发与迁移脚本、本地 MCP Demo
├── infrastructure/       配置、SQLite 模型与兼容迁移
├── prompts/              System、Memory、Summary、RAG、Planning 提示词
├── evaluation/           离线检索与 Planner 评测入口
├── tests/eval/           固定文档与 20 条检索用例
├── tests/                单元与 API 集成测试
└── data/uploads/         UUID 命名的上传原文件
```

依赖方向：`apps/api → core → infrastructure`；前端只消费 HTTP/SSE，不决定检索结果或引用来源。

### 能力文件夹约定

| 目录 | 放什么 | 最小入口 |
|---|---|---|
| `skills/` | 独立 Skill 指令 | `<skill-id>/SKILL.md` |
| `plugins/` | 可统一开关的 Skill/MCP 组合清单 | `<plugin-id>/plugin.yaml` |
| `mcp_servers/` | 项目内置、经过审查的 MCP 实现 | `<server-id>/server.py` |
| `config/` | 用户手工添加的 MCP 连接配置 | `mcp_servers.yaml` |
| `data/artifacts/` | Agent 生成的 DOCX/PDF/PPTX/XLSX 成品 | UUID 目录，由程序管理 |

第三方 Skill、插件和 MCP 不要混放：纯 Skill 放 `skills/`，组合包放 `plugins/`，可信本地 MCP 实现才放 `mcp_servers/`。各目录内的 `README.md` 给出了具体格式。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat` | SSE 流式聊天 |
| GET/POST | `/api/conversations` | 会话列表 / 创建 |
| GET | `/api/conversations/{id}/messages` | 消息与持久化引用 |
| GET/POST | `/api/memories` | 记忆列表 / 添加 |
| POST | `/api/files` | 上传并在请求线程池内完成索引 |
| GET | `/api/documents` | 文档列表与状态 |
| GET | `/api/documents/{id}` | 文档信息与前 20 个 chunk |
| GET | `/api/documents/{id}/content` | 查看或下载原文件 |
| DELETE | `/api/documents/{id}` | 删除文档、chunk 和原文件 |
| GET | `/api/search?q=&limit=` | 混合检索预览 |
| POST | `/api/approval` | 批准或拒绝待执行的高风险工具 |
| GET | `/api/tools` | 已注册工具及固定风险等级 |
| GET/POST | `/api/activities` | Activity 列表 / 创建 |
| GET | `/api/activities/{id}/runs` | Activity 的 Agent Run 历史 |
| POST | `/api/activities/{id}/pause` | 暂停计划 |
| POST | `/api/activities/{id}/resume` | 恢复计划 |
| POST | `/api/activities/{id}/run-now` | 立即排队执行 |
| DELETE | `/api/activities/{id}` | 删除非运行中的 Activity |
| GET | `/api/conversations/{id}/plans` | 会话最近 20 个 Plan 与步骤 |
| GET | `/api/activities/{id}/plans` | Activity 的 Plan 历史 |
| GET | `/api/plans/{id}` | Plan 与所有版本步骤详情 |
| GET | `/api/capabilities` | 当前启动快照中的只读能力列表 |
| GET | `/api/skills` | 全部 Skill 及启用、依赖和格式状态 |
| GET | `/api/skills/catalog` | Skill 目录版本、完整性和数量 |
| POST | `/api/skills/refresh` | 不重启服务重新扫描 Skill 目录 |
| POST | `/api/skills/import-folder` | 校验并导入浏览器选择的普通 Skill 文件夹 |
| POST | `/api/skills` | 创建标准本地 Skill 文件夹 |
| PATCH | `/api/skills/{id}` | 启用或关闭 Skill |
| DELETE | `/api/skills/{id}` | 将本地 Skill 移入可恢复回收目录 |
| GET/POST | `/api/mcp-servers` | MCP Server 列表 / 保存配置 |
| POST | `/api/mcp-servers/test` | 保存前测试 MCP 连接和工具发现 |
| POST | `/api/mcp-servers/refresh` | 热刷新用户 MCP 配置 |
| PATCH/DELETE | `/api/mcp-servers/{name}` | 启停 / 删除用户 MCP Server |
| GET | `/api/plugins` | 已安装声明式插件列表 |
| POST | `/api/plugins/import-folder` | 导入包含 plugin.yaml 的普通文件夹 |
| POST | `/api/plugins/refresh` | 热刷新插件目录 |
| PATCH/DELETE | `/api/plugins/{id}` | 启停 / 可恢复删除插件 |
| GET | `/api/artifacts` | 最近生成文件列表 |
| GET | `/api/artifacts/{id}` | 下载生成文件 |
| GET | `/api/settings` | 读取脱敏后的 Agent、模型与工作区配置 |
| PATCH | `/api/settings/{agent|model|workspace}` | 分项保存并应用运行时设置 |
| POST | `/api/settings/model/test` | 测试模型连接但不保存 |
| GET | `/api/settings/directories` | 本机编码工作区文件夹浏览 |

除 `rag.retrieved` 外，工具系统使用以下 SSE 事件：

```text
agent.status / tool.started / tool.completed
approval.required / approval.completed
plan.created / plan.step.started / plan.step.completed / plan.step.blocked
plan.replanned / plan.completed / plan.failed
```

无工具调用时，既有聊天事件和消息保存行为保持兼容。

## 验证

```powershell
uv run pytest -q
uv run python -m evaluation.rag
uv run python -m evaluation.planner

cd apps\web
npm run lint
npm run build
```

当前验收结果：`118 passed, 1 skipped`；跳过项仅为当前 Windows 环境无权创建符号链接。RAG 与 Planner 固定评测保持通过；前端 Lint、TypeScript 和生产构建均通过。

## 当前边界

P12 仍面向本机单用户、单个默认 Agent、单 API 进程和单 Activity Worker。运行时设置保存在本地忽略目录；文件夹浏览 API 不应暴露到公网。模型统一使用 OpenAI Chat Completions 兼容层；尚未提供多 Agent 预设、厂商专属参数、Git/URL 自动拉取和在线市场。
