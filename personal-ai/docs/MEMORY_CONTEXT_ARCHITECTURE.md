# Personal AI 上下文、分层记忆与意图识别设计

## 1. 结论

Personal AI 的信息系统采用五层逻辑架构：

```text
工作状态       Agent 当前正在做什么、做到哪一步
短期上下文     当前会话最近说了什么
情景记忆       过去做过什么、结果如何
语义记忆       用户偏好、项目约定和长期事实
知识库         文档、代码说明和外部资料
```

五层共享 PostgreSQL 作为事实数据库，情景记忆、语义记忆和知识库使用 pgvector 辅助语义检索。五层是职责划分，不是五套数据库，也不应全部塞进同一张向量表。

当前项目已经具备会话、消息、摘要、Agent Run、Plan、ToolRun、长期记忆、RAG 和 pgvector 基础能力。后续重点不是继续增加数据库，而是补齐记忆作用域、冲突处理、生命周期、Checkpoint 和统一意图路由。

## 2. 设计目标

本设计解决以下问题：

- 长对话不会无限携带全部历史，而是按模型窗口安全装配上下文；
- 区分当前任务状态、短期聊天、长期事实和外部知识；
- 只把值得长期保存的信息写入长期记忆；
- 防止一次性要求污染长期偏好；
- 防止不同项目的约定互相干扰；
- 新旧记忆冲突时可以替换、失效和追溯；
- Agent 中断或重启后可以恢复工作状态；
- 每次回答能够说明使用了哪些记忆、资料和工作状态；
- 意图识别只负责路由，不绕过工具权限、审批和安全限制。

## 3. 非目标

当前阶段不做以下设计：

- 不拆分为多个独立数据库服务；
- 不引入独立向量数据库；
- 不继续维护 SQLite 运行或测试兼容，schema 只通过 PostgreSQL + Alembic 演进；
- 不保存或展示模型隐藏的逐字思维链；
- 不把完整 Prompt 永久保存为所谓“上下文库”；
- 不让向量相似度直接决定工具授权；
- 不为了未来规模提前引入分布式消息队列和多 Worker；
- 不把所有消息自动转化为长期记忆。

## 4. 当前状态

| 能力 | 当前实现 | 状态 |
|---|---|---|
| 数据库 | 正式库 PostgreSQL 5432，隔离测试库 PostgreSQL 5433 | 已完成 |
| 会话 | `conversations`、`messages` | 已完成 |
| 短期上下文 | 最近消息、摘要、token 预算裁剪、候选/使用/裁剪统计 | 已完成 |
| 模型上下文容量 | 按所选模型窗口和输出预留动态计算 | 已完成 |
| 工作状态 | `agent_runs`、`plans`、`plan_steps`、`tool_runs` | 已完成 |
| Checkpoint | `checkpoints`、启动恢复、显式继续、ToolRun 幂等复用 | 已完成 |
| 长期记忆 | `memories`，支持 `episodic/semantic/profile` | 基础完成 |
| 记忆向量 | pgvector `vector(512)` + HNSW | 已完成 |
| 记忆治理 | 作用域、冲突、替换、过期、使用反馈 | 已完成 |
| 知识库 | `documents`、`document_chunks`、BM25 + pgvector + RRF | 基础完成 |
| 意图识别 | 规则短路、长尾 RAG 门控、模型工具选择、显式 direct/planned | 已完成 |
| 统一意图路由 | 稳定结构化输出、模糊请求轻量分类、低置信度回退 | 已完成 |

## 5. 总体架构

```text
用户请求
   │
   ▼
意图路由
   ├── 回答类
   ├── 知识检索类
   ├── 记忆管理类
   ├── 软件开发类
   └── 工具执行类
   │
   ▼
上下文装配器 core/chat/context.py
   ├── 工作状态：AgentRun / Plan / Checkpoint
   ├── 短期上下文：Messages / Summary
   ├── 情景记忆：Memories(kind=episodic)
   ├── 语义记忆：Memories(kind=semantic/profile)
   └── 知识库：Documents / DocumentChunks
   │
   ▼
LLM Gateway
   │
   ├── 直接回答
   └── 受控工具执行 → 审批 → ToolRun → 验证
   │
   ▼
结果保存、记忆候选提取、Checkpoint 更新
```

所有 LLM 调用继续经过 `core/chat/gateway.py`，所有上下文继续经过 `core/chat/context.py`，所有工具执行继续经过共享 Executor。

## 6. 五层详细设计

### 6.1 工作状态

工作状态回答的是：

> Agent 当前正在执行什么任务、完成了哪些步骤、接下来要做什么？

工作状态不是长期记忆，不通过向量相似度召回。它应根据当前 `run_id`、`conversation_id` 或 `activity_id` 精确读取。

现有数据：

- `agent_runs`：一次 Agent 执行；
- `plans`：任务目标、版本和整体状态；
- `plan_steps`：计划步骤和执行结果；
- `tool_runs`：工具调用、风险、审批和结果。

需要新增 `checkpoints`：

```text
checkpoints
├── id
├── run_id
├── plan_id
├── step_id
├── sequence
├── state_json
├── workspace_snapshot_json
├── capability_version
├── status
└── created_at
```

`state_json` 只保存恢复任务需要的结构化状态，例如：

```json
{
  "goal": "为项目增加登录功能",
  "current_step": 3,
  "completed_steps": [1, 2],
  "pending_approval_id": null,
  "relevant_files": ["apps/api/auth.py"],
  "last_observation": "后端测试通过，前端尚未接入"
}
```

Checkpoint 不保存隐藏思维链，也不保存无边界的工具输出。工具原始结果继续由 ToolRun/Artifact 管理，Checkpoint 只保存恢复摘要和引用。

`workspace_snapshot_json` 只允许保存文件路径、内容哈希、Git HEAD、工作树状态和 Artifact/Diff 引用，不保存完整文件内容或工作区快照，避免大项目撑大数据库。

Checkpoint 表本身不能保证安全恢复，还必须定义以下恢复语义：

1. 当前单进程应用启动时，把数据库中遗留的 `running` Run 标记为 `interrupted`，释放“单会话只能有一个 running Run”的部分唯一索引；
2. 进程内等待中的 Approval 不可恢复，启动时统一失效，恢复到相关步骤后必须重新申请审批；
3. 用户显式选择恢复后，把同一 `run_id` 从 `interrupted` 重新切换为 `running`，保持一条连续审计链；
4. 从最新有效 Checkpoint 恢复 Plan 版本、当前步骤和必要引用；
5. 对照持久化 ToolRun 判断步骤内哪些动作已经成功，不能只相信 `completed_steps`；
6. 已成功的高风险工具调用必须跳过，未完成或结果不确定的调用重新请求确认。

为此，`tool_runs` 需要增加稳定的 `idempotency_key`：

```text
run_id
+ plan_version
+ step_id
+ tool
+ normalized_args_hash
```

数据库对 `idempotency_key` 建立唯一约束。恢复前先查询对应 ToolRun：`completed` 直接复用已保存结果，`running/failed/cancelled` 不得当成成功。这样才能防止恢复时重复写文件、提交表单或执行其他高风险动作。

### 6.2 短期上下文

短期上下文回答的是：

> 当前会话最近讨论了什么？

数据来源：

- `messages`：用户与助手消息；
- `conversations.summary`：较早消息的增量摘要；
- 当前用户输入；
- 当前消息关联的图片和附件。

装配规则：

1. 先获取所选模型的真实上下文窗口；
2. 为模型输出预留 token；
3. 加入 System Prompt 和安全规则；
4. 加入当前用户消息；
5. 按预算加入工作状态、相关记忆和知识片段；
6. 从最近向较早加入会话消息；
7. 较早内容使用摘要，不直接携带完整历史；
8. 最终再次计算 token，保证不超过硬上限。

短期上下文不会永久增长。数据库可以保存完整消息历史，但每次模型调用只使用预算内的一部分。

### 6.3 情景记忆

情景记忆回答的是：

> 过去发生过什么？做过哪些任务？结果如何？

使用 `memories.kind = episodic` 保存，例如：

- “P13 数据库迁移已完成”；
- “上次为 JQ 项目修复了上下文滚动问题”；
- “用户否决了使用独立向量数据库的方案”。

不应保存：

- 当前正在执行第几步；
- 临时命令输出；
- 未完成任务的瞬时状态；
- 可以从 ToolRun、Git 或 Artifact 精确读取的原始数据。

情景记忆默认与项目或会话相关，不应自动成为全局用户事实。

### 6.4 语义记忆

语义记忆回答的是：

> 哪些事实、偏好和约定在未来仍然有效？

继续使用：

- `kind = profile`：用户身份、稳定偏好和交互要求；
- `kind = semantic`：项目约定和长期事实。

示例：

```text
用户喜欢中文回答
用户希望高风险工具执行前确认
JQ 项目使用 PostgreSQL + pgvector
项目后端端口为 8787
```

一次性表达必须识别为临时要求：

```text
“这次详细解释一下”             → 不写入全局偏好
“以后都详细解释”               → 可写入 profile
“这个项目统一使用 PostgreSQL”   → 写入 project scope
```

### 6.5 知识库

知识库回答的是：

> 用户提供的资料或项目文档中写了什么？

现有结构继续保持：

- `documents`：文件元数据、状态、模型和维度；
- `document_chunks`：文本切片、来源定位和 `vector(512)`；
- pgvector HNSW：向量候选；
- jieba/BM25：中文关键词候选；
- RRF：融合排序；
- citations：回答实际使用的来源。

知识库不等于长期记忆。文档内容应保留来源和引用，不应因为被检索过就自动变成用户偏好。

## 7. 长期记忆目标模型

现有 `memories` 表继续使用，不拆成多张表。建议分阶段增加以下字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `scope_type` | varchar | `global/project/conversation` |
| `scope_key` | varchar not null | `global` 或对应项目/会话 ID |
| `status` | varchar | `active/superseded/expired` |
| `supersedes_id` | FK nullable | 当前记忆替代的旧记忆 |
| `content_hash` | varchar | 内容级快速去重 |
| `usage_count` | integer | 实际装入上下文的次数 |
| `last_used_at` | timestamptz | 最近一次实际使用时间 |
| `expires_at` | timestamptz nullable | 可过期记忆的失效时间 |
| `extraction_version` | varchar | 提取规则或 Prompt 版本 |
| `embedding_version` | varchar | 向量生成版本 |

保留现有字段：

```text
kind
content
normalized_key
source_conversation_id
importance
confidence
is_active
embedding
embedding_model
embedding_dim
embedded_at
created_at
updated_at
```

`status` 与 `is_active` 是两套互补机制，职责固定：`status` 由系统按记忆生命周期管理（`active/superseded/expired`），记忆界面的“停用”开关只翻转 `is_active`，不改动 `status`。召回硬过滤要求两个条件同时通过；界面停用等价于对召回不可见，替换与过期只通过 `status` 表达。

### 7.1 作用域规则

```text
global
├── scope_key = global
└── 跨项目稳定有效的用户偏好与身份信息

project
├── scope_key = project_id
└── 只对指定项目有效的技术约定、架构决定和项目事实

conversation
├── scope_key = conversation_id
└── 只对当前会话后续轮次有效、但需要跨摘要保留的信息
```

召回时按以下范围过滤：

```text
当前会话 scope
∪ 当前项目 scope
∪ global scope
```

其他项目的记忆默认不可见。

`scope_key` 不允许为 `NULL`。如果提取模型无法可靠判断作用域，默认写入当前 `conversation`，将错误影响限制在最小范围；只有用户明确声明长期偏好、项目约定，或同一事实经过多次确认后，才允许提升为 `project/global`。作用域提升必须产生可审计的更新，不在后台静默扩大可见范围。

现有数据库中的旧记忆迁移时采用保守回填：有 `source_conversation_id` 的记忆先进入对应 conversation scope；没有来源的人工记忆进入 global scope。之后通过用户确认或规则评审提升作用域，不使用一次新的 LLM 分类批量猜测全局范围。

回填上线后召回会明显变安静：原有带来源的记忆只在各自来源会话内可见，新会话只剩 global 范围。这是迁移的预期行为而不是召回退化；在记忆设置页逐条确认提升作用域后即可恢复可见。确定性的中间档允许在回填时使用：记忆来源会话已归属某个 project（`conversations.project_id` 非空）时，可以直接回填到该 project scope，这不依赖 LLM 猜测；但不做进一步的批量推断。

### 7.2 唯一约束与查重

现有唯一约束 `(user_id, normalized_key)` 会阻止不同项目保存同名约定，必须在阶段 A 的 Alembic migration 中替换为：

```text
(user_id, scope_type, scope_key, normalized_key)
```

使用非空 `scope_key` 是为了避免 PostgreSQL 把多个 `NULL` 视为互不相同，导致 global scope 出现重复记忆。`save_memories` 的查重查询也必须使用同样的四个字段，不能继续只按 `(user_id, normalized_key)` 查找。

### 7.3 状态与替换

记忆不直接覆盖旧记录，而是保留可追溯关系：

```text
旧记忆：项目数据库使用 SQLite
status = superseded

新记忆：项目数据库使用 PostgreSQL
status = active
supersedes_id = 旧记忆 ID
```

正常召回只读取 `active` 且未过期的记忆。设置页可以查看替换关系，但默认不展示失效记忆。

## 8. 记忆写入流程

```text
对话或任务完成
   ↓
提取记忆候选
   ↓
敏感信息和用户拒绝记忆检查
   ↓
判断 kind 与 scope
   ↓
重要性、置信度和长期价值检查
   ↓
精确键去重 + 语义近重复检查
   ↓
冲突判断
   ├── 新事实替代旧事实
   ├── 补充已有事实
   ├── 判定为一次性信息，不保存
   └── 无冲突，新建记忆
   ↓
生成向量并事务写入
```

scope 判断采用“保守写入、显式提升”原则：无法确定时写入 conversation scope；同一事实跨会话重复出现，只生成提升候选，不自动升级；用户明确说“以后都这样”时才允许直接写入 global profile。

### 8.1 保存条件

满足以下一种或多种条件才考虑长期保存：

- 用户明确说“记住”“以后都这样”；
- 稳定身份、偏好或沟通方式；
- 已确认的项目架构决定；
- 未来任务大概率重复使用的事实；
- 已完成任务的重要结果。

以下内容默认不保存：

- 问候和闲聊；
- 一次性格式要求；
- 未确认的推测；
- 工具原始输出；
- 密码、API Key、Token、身份证、银行卡等敏感数据；
- 用户明确要求不要记录的内容。

### 8.2 失败处理

- 记忆提取失败不能影响聊天结果保存；
- 向量生成失败时可以先保存文本，向量字段为 `NULL`；
- 无向量记忆仍可以通过关键词召回；
- 后台任务可以补齐缺失向量；
- 文本发生改变时旧向量立即失效，完成重建后再参与向量检索。

## 9. 记忆召回与排序

### 9.1 硬过滤

召回前必须先过滤：

```text
user_id 匹配
status = active
is_active = true
未过 expires_at
scope 属于当前 global/project/conversation
embedding_model 与 embedding_dim 匹配
```

### 9.2 候选生成

同时生成两类候选：

- pgvector HNSW 语义候选；
- 数据库词法候选：normalized_key 精确匹配、`ILIKE` 子串匹配和 `pg_trgm` 模糊匹配。

向量检索负责语义相近，关键词检索负责专有名词、路径、版本号和精确事实。任何一方都不能单独成为最终结果。

当前实现已经改为数据库候选生成：`normalized_key` 精确匹配、`ILIKE`/中文二元词元、`pg_trgm` 与 pgvector HNSW 并行召回，再统一排序；不再扫描最近更新的 200 条记忆。中文短语、文件路径和版本号优先使用 `pg_trgm` 与词元通道，不依赖 PostgreSQL 默认 `tsvector` 完成中文分词。

建议候选流程：

```text
normalized_key / 精确短语候选
∪ pg_trgm / ILIKE 词法候选
∪ pgvector HNSW 语义候选
→ 去重
→ 统一排序
→ token 预算裁剪
```

### 9.3 初始排序公式

第一版可以使用可解释的加权排序：

```text
score =
    0.40 × semantic_similarity
  + 0.20 × lexical_score
  + 0.15 × importance
  + 0.10 × confidence
  + 0.05 × scope_priority
  + 0.05 × recency
  + 0.05 × usage_signal
```

权重只是初始值，最终以固定评测集为准。项目作用域匹配优先于全局泛化，明确精确匹配优先于模糊向量相似。

### 9.4 使用反馈

只有真正装入模型上下文的记忆才算一次使用：

```text
usage_count += 1
last_used_at = now
```

仅进入候选集但被 token 预算裁掉的记忆不计入使用次数。

## 10. 意图识别设计

意图识别负责决定需要哪些信息源和执行方式，不直接负责回答，也不直接授权工具。

建议输出稳定的结构化结果：

```json
{
  "intent": "software_development",
  "action": "modify_code",
  "needs_memory": true,
  "needs_knowledge": false,
  "needs_workspace": true,
  "needs_plan": true,
  "candidate_tools": ["coding_search", "coding_edit_exact"],
  "risk_hint": "high",
  "confidence": 0.91
}
```

### 10.1 初始意图集合

```text
conversation             普通交流
knowledge_query          查询个人资料库
memory_management        查看、增加、修改或删除记忆
software_development     分析或修改软件项目
task_execution           使用工具完成实际任务
current_information      需要外部实时信息
calculation              确定性计算
settings_change          修改 Agent、模型或工作区设置
```

### 10.2 路由规则

- 明确规则优先，例如问候、纯计算、时间、记忆管理、设置修改和显式知识库请求；
- 规则命中的请求直接短路，不触发任何额外 LLM 分类；
- 只有无法由规则稳定判断、且路由结果会实际改变检索或执行方式的请求，才调用轻量模型分类；
- 简单聊天默认保持原有延迟，不得为了得到一个 intent 标签增加一次模型往返；
- 低置信度时保持直接回答或请求必要澄清；
- `risk_hint` 只是提示，最终风险以 Tool 注册和 Executor 策略为准；
- Prompt 注入不得改变工具白名单和审批规则；
- 意图结果可以决定是否检索，但不能伪造 RAG 引用。

## 11. 上下文装配策略

上下文预算按“硬约束优先、相关性优先”分配：

```text
模型上下文窗口
  - 输出预留
  - System Prompt 与安全规则
  - 当前用户输入
  - 工具 Schema（需要时）
  = 可分配输入预算
```

建议装配优先级：

1. System Prompt、安全规则和当前用户输入；
2. 当前工作状态和待审批信息；
3. 与意图直接相关的项目/全局记忆；
4. 用户明确选择的附件；
5. RAG 检索片段；
6. 最近会话消息；
7. 会话摘要；
8. 低相关补充记忆。

具体顺序允许按意图调整。例如普通聊天优先最近消息，知识问答优先附件与 RAG，任务恢复优先 Checkpoint。

### 11.1 上下文可观察性

前端只展示可验证信息，不展示隐藏思维链：

```text
上下文上限：128K
本轮预计使用：21K
剩余：107K（83.6%）

使用内容：
- 最近消息 14 条
- 会话摘要 1 条
- 长期记忆 3 条
- 知识库片段 5 条
- 工具定义 8 个
```

可以进一步展示每条记忆和资料的来源，但不得在前端自行选择或拼接上下文。

## 12. 数据库索引建议

项目只支持 PostgreSQL。正式库和自动化测试库都通过同一套 Alembic revision 建表，测试库使用独立端口和数据库名，不存在 `_migrate_sqlite_pXX` 或 SQLite 表重建路径。

现有向量索引继续保留：

```sql
CREATE INDEX ix_memories_embedding_hnsw
ON memories USING hnsw (embedding vector_cosine_ops)
WHERE embedding IS NOT NULL;

CREATE INDEX ix_document_chunks_embedding_hnsw
ON document_chunks USING hnsw (embedding vector_cosine_ops);
```

增加作用域后建议建立普通索引：

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE memories DROP CONSTRAINT uq_memories_user_key;
ALTER TABLE memories ADD CONSTRAINT uq_memories_scope_key
UNIQUE (user_id, scope_type, scope_key, normalized_key);

CREATE INDEX ix_memories_recall_scope
ON memories (user_id, scope_type, scope_key, status, kind);

CREATE INDEX ix_memories_content_trgm
ON memories USING gin (content gin_trgm_ops)
WHERE status = 'active' AND is_active = true;

CREATE INDEX ix_memories_expiration
ON memories (expires_at)
WHERE expires_at IS NOT NULL AND status = 'active';

CREATE INDEX ix_checkpoints_run_sequence
ON checkpoints (run_id, sequence DESC);

CREATE UNIQUE INDEX uq_tool_runs_idempotency_key
ON tool_runs (idempotency_key);
```

普通过滤字段使用 B-tree，语义相似度使用 HNSW。不能用向量索引代替用户、项目、状态和过期时间过滤。

## 13. API 与界面建议

### 13.1 记忆 API

现有 CRUD 保持兼容，后续增加：

```text
GET    /api/memories?scope_type=&scope_key=&kind=&status=
PATCH  /api/memories/{id}/scope
POST   /api/memories/{id}/supersede
POST   /api/memories/{id}/expire
GET    /api/memories/{id}/history
```

### 13.2 记忆界面

记忆页面按作用域分组：

```text
全局记忆
├── 用户偏好
└── 长期事实

项目记忆
├── JQ
├── Personal AI
└── 其他项目

情景记忆
└── 最近完成任务
```

每条记忆展示类型、作用域、重要性、置信度、来源、最近使用时间和状态。用户可以停用、纠正、移动作用域或查看被哪条新记忆替代。

### 13.3 Agent 过程界面

展示：

- 当前任务与步骤；
- 正在调用的工具；
- 读取或修改的文件；
- 等待审批；
- 最近 Checkpoint；
- 停止和恢复状态。

不把模型自由生成的“我正在思考……”文本当成可靠执行状态，界面状态必须来自后端事件和持久化记录。

## 14. 安全与隐私

- 继续执行现有敏感信息过滤；
- 用户明确说“不记住”时整轮跳过自动记忆提取；
- 删除记忆时同步处理向量；
- API 不返回模型密钥和私密 MCP 配置；
- 不把工作区敏感文件自动写入知识库或长期记忆；
- 项目作用域必须在后端过滤，前端参数不能绕过；
- Checkpoint 中的工具参数保存脱敏摘要；
- 数据库备份必须与应用密钥分开管理；
- 未来多用户部署前增加认证和数据库行级隔离。

## 15. 分阶段实施

### 阶段 A：记忆作用域与生命周期（已完成）

- 通过 Alembic 为 `memories` 增加 scope、status、supersedes、usage 和 expiration 字段；
- 按保守规则回填旧数据，并把唯一约束替换为 `(user_id, scope_type, scope_key, normalized_key)`；
- 修改 `save_memories`，查重与更新必须包含 scope；
- 修改自动提取结果，要求输出 kind、scope 和长期价值；
- 实现精确去重、语义近重复和冲突替换；
- 增加 `pg_trgm`/ILIKE/normalized_key 数据库词法召回，不再只扫描最近 200 条；
- 召回时执行作用域和状态硬过滤；
- 保持现有记忆 API 兼容。

验收：不同项目的记忆不会串用，一次性要求不会污染全局偏好，新事实可以替换旧事实。

### 阶段 B：工作状态 Checkpoint（已完成）

- 新增 `checkpoints`；
- 在计划步骤完成、审批等待和安全中断时保存恢复点；
- 启动时把遗留 `running` Run 标记为 `interrupted`，并使进程内旧 Approval 失效；
- 为 ToolRun 增加幂等键，恢复时以已完成 ToolRun 对账，不能只依赖 `completed_steps`；
- workspace snapshot 只保存路径、哈希、Git 状态和 Artifact/Diff 引用；
- 用户显式恢复后重新进入原 Run 的计划循环；
- 前端显示最近恢复点和恢复结果。

验收：任务在步骤之间中断后可以继续，且不会重复已完成的高风险工具调用。

### 阶段 C：统一意图路由（已完成）

- 增加规则优先的 Intent Router；
- 规则命中直接返回，只有模糊且影响路由的请求才调用轻量模型；
- 输出稳定结构化意图；
- 根据意图决定记忆、RAG、工作区和 Planner 是否参与；
- 保留 Executor 的最终权限裁决。

验收：固定意图测试集准确，规则可判定的简单请求不增加模型往返，低置信度安全回退，不改变工具审批边界。

### 阶段 D：评测与可观察性（已完成）

- 建立记忆提取、去重、冲突和召回固定测试集；
- 记录候选、实际使用和被预算裁剪的原因；
- 前端显示本轮上下文组成；
- 根据评测结果调整召回权重。

验收：能够量化错误记忆率、重复率、Recall@K、作用域误召回率和上下文实际使用率。

### 15.1 实际落地清单

- Alembic revision `20260823_02` 完成记忆作用域、生命周期、替换链和检索索引；
- Alembic revision `20260823_03` 完成 Checkpoint、Run 原始输入/意图快照、ToolRun 计划定位与幂等键；
- 应用启动时清理进程内 Approval，并把数据库遗留 `running` 规划任务安全转为 `interrupted`；
- `POST /api/chat/{run_id}/resume` 只恢复同一 Run，能力版本不一致时拒绝恢复；
- `GET /api/runs/{run_id}/checkpoints` 与 `GET /api/conversations/{conversation_id}/checkpoints` 提供只读恢复历史；
- 前端展示最近 Checkpoint、恢复按钮、意图类型以及记忆/知识候选、实际使用和裁剪数量；
- 固定评测入口为 `uv run python -m evaluation.rag`、`uv run python -m evaluation.intent` 和 `uv run python -m evaluation.memory`；
- 自动化测试和评测只允许连接数据库名为 `personal_ai_test` 的 5433 隔离测试库。

### 15.2 2026-08-23 验证基线

- 后端：186 passed，1 skipped；
- 前端：`npm run build` 通过，`npm run lint` 0 error（保留 2 个既有 `<img>` 性能提示）；
- 意图评测：Accuracy 1.000，规则短路率 1.000，规则用例模型往返 0；
- 记忆评测：错误记忆率 0、重复率 0、Recall@3 1.000、作用域误召回率 0、冲突处理率 1.000、上下文实际使用率 1.000；
- RAG 评测：Recall@1/3/5、MRR、章节命中和关键词命中均为 1.000。

## 16. 核心验收场景

### 场景一：临时要求不污染偏好

```text
用户：这一次请回答详细一点。
```

预期：只作用于当前请求，不产生 global profile 记忆。

### 场景二：明确长期偏好

```text
用户：以后执行删除和推送前都要让我确认。
```

预期：保存为 global profile；但最终工具审批仍由权限系统强制执行。

### 场景三：项目约定隔离

```text
JQ 项目：数据库使用 PostgreSQL。
另一个项目：数据库使用 SQLite。
```

预期：两条 project semantic 记忆即使 `normalized_key` 相同也可以写入，分别生效且不互相召回。

### 场景四：新事实替代旧事实

```text
旧：项目数据库使用 SQLite。
新：项目已经迁移到 PostgreSQL。
```

预期：旧记忆变为 superseded，新记忆 active，保留替换关系。

### 场景五：任务恢复

```text
Agent 已修改文件并完成测试，准备生成 diff 时应用重启。
```

预期：启动时旧 Run 先进入 interrupted；用户恢复后从 Checkpoint 继续，并根据 ToolRun 幂等键跳过已经成功的写文件和高风险步骤。

### 场景六：知识与记忆分离

```text
文档写着“推荐使用 Redis”，用户没有确认采用。
```

预期：内容只作为带引用的知识片段，不自动成为“项目使用 Redis”的长期事实。

## 17. 实施原则

- 先完成作用域和生命周期，再增加复杂排序；
- 先使用现有 PostgreSQL 和 pgvector，不引入新数据库；
- 正式与测试环境均使用 PostgreSQL，不维护 SQLite 双轨；
- 工作状态使用精确查询，长期记忆和知识库才使用语义检索；
- 数据库保留完整历史，模型上下文只装入预算内相关内容；
- 自动记忆必须可查看、可停用、可纠正、可追溯；
- 意图识别只做路由，Executor 始终掌握工具授权；
- 所有新增行为必须有固定测试和可解释日志。

## 18. 最终目标

完成本设计后，Personal AI 应能够明确区分：

```text
“我现在做到哪一步”       → 工作状态
“我们刚才说了什么”       → 短期上下文
“以前完成过什么”         → 情景记忆
“用户和项目长期是什么样” → 语义记忆
“资料或代码中写了什么”   → 知识库
```

这些信息由上下文装配器按当前意图、作用域、相关性和模型 token 预算统一组织，形成可持续扩展的软件开发与任务执行 Agent 基础。
