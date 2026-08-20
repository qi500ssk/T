# Personal AI Agent（P3：开始做事）

Chat-first Personal AI：支持流式聊天、长期记忆、个人资料知识库，以及经过权限控制的本地工具执行。

完整交付说明见 [P3 阶段开发报告](docs/P3.md)。

## 已完成功能

- FastAPI + SSE 流式聊天，会话、消息与 Agent Run 持久化
- 会话增量摘要、长期记忆提取/召回/启停和敏感信息过滤
- PDF、DOCX、TXT、Markdown 安全上传与 UUID 原文件存储
- 文档解析、结构化分块、tokenizer/字符/页数/解压大小/超时限制
- 本地 `bge-small-zh-v1.5`、OpenAI-compatible 和 Mock Embedding Provider
- 向量相似度 + BM25 + RRF 混合检索
- Memory、RAG、Summary、Recent Messages 独立预算与总 token 硬上限
- `rag.retrieved` SSE 事件、引用白名单、消息引用持久化
- 对话 / 记忆 / 知识库三个主视图，支持上传、状态、预览、检索和删除
- 固定 20 条中文检索评测，输出 Recall@1/3/5、MRR、章节与关键词命中率
- OpenAI 兼容 Tool Calling，多回合执行后由模型基于工具结果回答
- `get_time`、安全计算、沙箱文件读取和审批后写入
- SKILL.md 指令加载与请求级工具白名单
- 工具状态、写入审批卡片、`tool_runs` 执行记录和结构化日志

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

默认使用本地 BGE 路径。若只需轻量联调，可在 `.env` 设置 `EMBEDDING_PROVIDER=mock`；聊天默认 `LLM_PROVIDER=mock`，无需 API Key。

## 目录

```text
personal-ai/
├── apps/api/             FastAPI 装配、聊天 SSE、知识库 API
├── apps/web/             Next.js UI（对话、记忆、知识库）
├── core/
│   ├── rag/              解析、分块、入库、混合检索
│   ├── embedding.py      Embedding Provider
│   ├── context.py        Memory/RAG/Summary/历史预算组装
│   ├── tools.py          工具注册、安全校验与沙箱执行
│   ├── skills.py         SKILL.md 加载与工具白名单
│   ├── permissions.py    单进程审批等待器
│   └── agent.py          Run 生命周期、工具循环、SSE 和持久化
├── skills/               启用的本地 Skill 指令包
├── infrastructure/       配置、SQLite 模型与兼容迁移
├── prompts/              System、Memory、Summary、RAG 提示词
├── evaluation/           离线检索评测入口
├── tests/eval/           固定文档与 20 条检索用例
├── tests/                单元与 API 集成测试
└── data/uploads/         UUID 命名的上传原文件
```

依赖方向：`apps/api → core → infrastructure`；前端只消费 HTTP/SSE，不决定检索结果或引用来源。

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

除 `rag.retrieved` 外，P3 新增以下 SSE 事件：

```text
agent.status / tool.started / tool.completed
approval.required / approval.completed
```

无工具调用时，既有聊天事件和消息保存行为保持兼容。

## 验证

```powershell
uv run pytest -q
uv run python -m evaluation.rag

cd apps\web
npm run lint
npm run build
```

当前验收结果：`53 passed, 1 skipped`；跳过项仅为当前 Windows 环境无权创建符号链接。前端 ESLint、TypeScript 和生产构建通过。

## 当前边界

P3 使用单进程内存保存待审批 waiter，适合单用户本地运行；服务重启恢复、多用户权限、动态风险、删除工具和外部连接留到后续阶段。P2 的 SQLite JSON 向量边界保持不变。
