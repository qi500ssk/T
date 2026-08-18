# Personal AI Agent（P2：理解资料）

Chat-first Personal AI：支持流式聊天、长期记忆与个人资料知识库，回答可携带可追溯的文档引用。

完整交付说明见 [P2 阶段开发报告](docs/P2.md)。

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
│   └── agent.py          Run 生命周期、SSE 和引用持久化
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

新增 SSE 事件在首个 `message.delta` 前发送：

```text
event: rag.retrieved
data: {"sources": [{"citation_id":"c1", "document_id":"...", "excerpt":"..."}]}
```

无检索结果时不发送该事件，P0/P1 客户端行为保持兼容。

## 验证

```powershell
uv run pytest -q
uv run python -m evaluation.rag

cd apps\web
npm run lint
npm run build
```

当前验收结果：`37 passed`；真实本地 BGE 的 20 条固定评测 `Recall@1/3/5 = 1.000`、`MRR = 1.000`。

## 当前边界

P2 使用 SQLite JSON 保存向量并在应用层计算相似度，适合单用户、小规模个人知识库。OCR、Reranker、Query Rewrite、异步索引 Worker、PostgreSQL/pgvector、认证与多租户留到后续阶段。
