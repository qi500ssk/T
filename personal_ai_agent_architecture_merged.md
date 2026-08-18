# Personal AI Agent：产品与系统架构设计（合并版 V1.0）

> 本文由两份同源设计文档合并而成：
>
> - 《Personal AI Agent 完整架构设计文档 V1.0》（docx，20 章，Chat-first 产品视角）
> - 《Personal AI Agent：分层架构设计与完整功能规划》（md，30 节，分层架构研究视角）
>
> 合并原则：以产品化主线（Agent Event Protocol、P0-P6 开发路线、验收标准、前端架构）为骨架，
> 融入分层架构细节（Character 示例、Context Engine 接口、Prompt 管理、易漏点清单、完整数据流）。
> 两份文档核心架构一致，本文不再区分来源。
>
> 核心定位：**Chat-first Personal AI Agent**。聊天是主要入口，但不是整个系统。
> 一个长期存在、能聊天、记忆用户、检索知识、使用 Skill / Tool / MCP，
> 并逐步具备主动活动能力的 Personal AI，最终形成 Character、Agent Runtime、Context、
> Memory、RAG、Skill、Tool、MCP、Activity 等能力。

---

## 1. 产品定位

聊天是主要入口，但不是整个系统。能力全景：

```text
Chat      主要交互入口
Character 身份、人格、偏好和关系
Memory    长期记住用户及过去的重要信息
RAG       理解用户和外部知识资料
Skill     描述如何完成一类事情
Tool      提供具体执行动作
MCP       标准化连接外部工具和服务
Activity  支持任务、定时、事件和后台活动
Agent Runtime 统一组织以上能力并完成 Agent Run
```

核心信念：

> Chat 是入口，不是整个系统。
> Memory 是"记住你"。
> RAG 是"知道你的资料"。
> Skill 是"知道怎么做一类事情"。
> Tool 是"具体执行动作"。
> MCP 是"连接外部世界"。
> Activity 是"持续做事情"。
> Agent Runtime 是"把这些东西组织起来的大脑"。
> Character 是"这个 AI 本身"。

---

## 2. 最终架构总览

```text
┌──────────────────────────────────────────────────────────────┐
│                         Client Layer                         │
│              Web / Mobile / Desktop / Voice                │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTPS / SSE / WebSocket
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                         API Layer                            │
│       Auth / Chat API / File API / Stream / User API        │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    Personal AI / Character                   │
│ Identity / Personality / Preferences / User Profile         │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                       Agent Runtime                          │
│ Agent Loop / State / Planning / Reflection / Interrupt      │
└───────────────┬──────────────────────┬───────────────────────┘
                │                      │
                ▼                      ▼
┌────────────────────────┐   ┌─────────────────────────────────┐
│    Context Engine      │   │       Activity Runtime          │
│ Recent / Memory / RAG  │   │ Chat / Task / Scheduled / Event │
│ Skill / Tool / Summary │   │ Background / Autonomous         │
└────────────────────────┘   └─────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│                         Model Layer                          │
│ LLM / Embedding / Reranker / Vision / STT / TTS             │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                     Capability Layer                         │
│ Skill → Tool Router → Native Tools / MCP                    │
└──────────────┬───────────────────────────────┬───────────────┘
               ▼                               ▼
       Native Tool Runtime                 MCP Layer
       Search / File / Code                MCP Client
       Calculator / etc.                   MCP Servers
               │                               │
               └───────────────┬───────────────┘
                               ▼
                     External World / Services

┌──────────────────────────────────────────────────────────────┐
│                         Data Layer                           │
│ SQL / Vector / Object Storage / Cache / Event Store          │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                  Cross-Cutting Infrastructure                │
│ Security / Permission / Approval / Audit / Observability /  │
│ Evaluation / Rate Limit / Secrets / Config / Feature Flags  │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 前端产品架构

前端不建议只做一个 ChatGPT Clone，而应设计成以 Chat 为核心入口的 **Personal AI Workspace**。

```text
┌─────────────────────────────────────────────────────────┐
│ Top Bar: Logo / Search / Model / User                  │
├───────────────┬─────────────────────────┬───────────────┤
│ Conversations │          Chat           │ Context Panel │
│ + New Chat    │     Message Stream      │ Memory        │
│ Today         │                         │ Files         │
│ Yesterday     │                         │ Sources       │
│ Projects      │                         │ Activity      │
├───────────────┴─────────────────────────┴───────────────┤
│ Composer: + / @ / File / Voice / Send                  │
└─────────────────────────────────────────────────────────┘
```

### 3.1 Chat 页面

- 流式输出
- Markdown / 代码 / 图片 / 文件
- 编辑、重试、重新生成、停止
- 来源 / 引用
- Agent Activity 状态（只展示安全、可解释的状态，不暴露内部隐藏推理）
- Tool / Skill 执行状态
- Approval Card（用户确认卡片）
- Tool 调用结果摘要

### 3.2 Memory 管理

- 查看 AI 记住的内容
- 编辑 / 删除 Memory
- 禁止某条信息继续长期记忆
- 查看 Memory 来源

### 3.3 Knowledge / RAG

- 上传 PDF / Word / TXT / Markdown
- 解析 → Chunk → Embedding → Index 状态展示
- Knowledge / Collection / Project 组织
- 回答中的来源引用

### 3.4 Skill Center

- Skill 描述与启用状态
- 所需工具
- 权限范围
- 版本

### 3.5 Activity

- Tasks
- Scheduled
- Events
- Background Activity
- Activity History

### 3.6 前端技术栈

```text
Next.js
React
TypeScript
Tailwind CSS
shadcn/ui
```

### 3.7 不应该放在前端

不要让前端决定：

```text
应该调用哪个 Tool
应该读取哪些 Memory
应该执行哪个 Skill
是否允许执行危险操作
```

这些必须由后端控制。前端只展示后端下发的状态。

---

## 4. API Layer

推荐 FastAPI。API 层负责：

```text
POST /chat            SSE 流式聊天
GET  /conversations   会话列表
POST /files           文件上传
GET  /memories        记忆列表
POST /memories        写入记忆
DELETE /memories/:id  删除记忆
GET  /skills          技能列表
GET  /tools           工具列表
POST /approval        审批结果回流
```

流式聊天用 SSE；如果以后需要服务端主动推送、实时状态同步，再考虑 WebSocket。

---

## 5. 前后端通信：Agent Event Protocol

不要让前端只接收纯文本。建议使用 SSE 传递**结构化 Agent Event**，使前端和 Agent Runtime 解耦——增加新事件不需要重写前端聊天逻辑。

### 事件类型

```text
run.started / run.completed / run.failed
message.started / message.delta / message.completed
context.started
memory.retrieved
rag.retrieved
skill.started / skill.completed
tool.started / tool.completed
approval.required / approval.completed
activity.created
agent.status（如 retrieving_memory）
```

### 事件示例

```json
{"type":"message.delta","content":"你好"}
{"type":"agent.status","status":"retrieving_memory"}
{"type":"tool.start","tool":"web_search"}
{"type":"approval.required","tool":"send_email","risk_level":"HIGH"}
{"type":"run.completed","run_id":"run_xxx","token_usage":{"total":1234}}
```

前端依据 `type` 渲染不同 UI（流式文本 / Tool 状态卡片 / Approval 卡片 / 来源引用）。

---

## 6. Conversation、Message 与 Agent Run

必须明确区分三个概念。**一次用户消息可能触发多次模型调用、RAG、Memory 和 Tool。**

```text
Conversation
 ├── Message
 └── AgentRun
       ├── LLM Call
       ├── Memory Retrieval
       ├── RAG Retrieval
       ├── Skill Run
       └── Tool Run
```

- **Conversation**：用户的会话，包含多条 Message；
- **Message**：一次用户输入或一条 AI 回复；
- **AgentRun**：一条用户消息触发的一次完整执行，有独立 `run_id`，内部可包含多次 LLM 调用和多次工具执行。

---

## 7. Character / Identity Layer

不要把 Agent 设计成 `LLM + Prompt`，而是：

```text
Character
├── Identity
├── Personality
├── User Profile
├── Preferences
├── Goals
└── Relationship State
```

### Identity 示例

```yaml
name: Assistant
role: Personal AI Assistant
language: zh-CN
```

### Personality

```text
语气
回答长度
幽默程度
正式程度
主动程度
```

### User Profile

保存用户偏好、语言、时区、常用设置、用户明确要求记住的信息。

> **敏感信息必须有明确的存储和权限策略，不应该因为"记忆功能"自动永久保存。**

---

## 8. Agent Runtime

这是整个系统的核心，负责统一编排所有能力。

```text
Agent Runtime
├── Agent Loop
├── State
├── Planner
├── Executor
├── Interrupt
├── Approval
├── Retry
└── Timeout
```

### 核心循环

```text
User Input
    ↓
Load State
    ↓
Build Context
    ↓
LLM
    ↓
Need Action?
 ┌──┴───────┐
No         Yes
 ↓           ↓
Answer    Skill / Tool / MCP
             ↓
          Execute
             ↓
        Observation
             ↓
          Update State
             ↓
            LLM
    ↓
Final Response
```

### 第一版必须限制

```text
最大执行步数 max_steps
Timeout
Retry 次数
Token / Cost Budget
Cancellation
Tool 权限
用户 Approval
```

第一版不要直接做"无限自主 Agent"。

---

## 9. Context Engine

这是项目中最值得独立成模块的一层。Context Engine 负责决定**什么信息进入当前模型上下文**，避免把全部历史直接塞给 LLM。禁止：

```python
messages = all_history
```

而是：

```text
Context Engine
├── System Context
├── Character Context
├── Recent Conversation
├── Conversation Summary
├── User Memory
├── RAG Results
├── Active Skill
├── Available Tools
├── Tool Results
└── Current Task State
```

最终链路：

```text
Context
    ↓
Context Policy
    ↓
Token Budget
    ↓
LLM
```

建议接口：

```python
context = context_engine.build(
    user_id=user_id,
    conversation_id=conversation_id,
    message=user_message,
    task_state=task_state,
)
```

**Token 预算裁剪必须在构建时完成**，否则长对话必然爆上下文。

---

## 10. Memory System

Conversation 不等于 Memory。Memory 是从对话中筛选出的**长期、有价值信息**。

```text
Memory
├── Working Memory       当前任务状态（正在做什么、计划、已完成、下一步）
├── Episodic Memory      过去发生的事件（2026-08-10 用户讨论过换工作）
├── Semantic Memory      长期事实（用户喜欢简洁回答）
├── User Profile         用户属性和偏好
└── Conversation Summary 历史会话摘要
```

### Memory Pipeline

```text
Conversation
    ↓
Memory Extractor
    ↓
Should Remember?
    ↓
Memory Candidate
    ↓
Importance / Confidence
    ↓
User Policy
    ↓
Store
```

**不要把每句话都存进长期记忆。**

---

## 11. RAG / Knowledge Layer

RAG 与 Memory 分开：**Memory 主要描述用户和过去经历；RAG 主要描述外部或用户提供的资料。**
两者可以共享向量基础设施，但业务逻辑必须分开。

### 数据流（Ingestion）

```text
PDF / Word / TXT / Markdown / Web
    ↓
Parser
    ↓
Chunking
    ↓
Embedding
    ↓
Vector Store
```

### 数据流（Retrieval）

```text
User Question
    ↓
Query Rewrite
    ↓
Retriever
    ↓
Reranker
    ↓
Relevant Chunks
    ↓
Context Engine
    ↓
LLM
```

---

## 12. Skill / Tool / MCP

### 12.1 Skill System

Skill 是"如何完成某一类事情"。

```text
Skill
├── Metadata
├── Instructions
├── Workflow
├── Required Tools
├── Input Schema
├── Output Schema
├── Permission
└── Version
```

目录示例：

```text
skills/
├── daily-review/
│   └── SKILL.md
├── document-summary/
│   └── SKILL.md
├── travel-planning/
│   └── SKILL.md
└── email-assistant/
    └── SKILL.md
```

**Skill 不应该直接操作数据库或第三方 API**，应经 Tool Router 转发。

### 12.2 Tool Layer

Tool 是 Agent 实际执行动作的接口。每个 Tool 必须定义：

```text
name
description
input_schema
output_schema
permission
timeout
risk_level
```

```text
Native Tools    calculator / file_read / file_write / web_search / time / weather
External Tools  Gmail / Calendar / Notion / GitHub
```

### 12.3 MCP Layer

MCP 是外部工具/资源的标准连接层：

```text
Agent
 ↓
Skill
 ↓
Tool Router
 ↓
MCP Client
 ↓
MCP Server
 ↓
External Service
```

```text
MCP Client
├── Server Discovery
├── Tool Discovery
├── Resource Discovery
├── Prompt Discovery
├── Connection Manager
├── Permission Manager
└── Timeout / Retry
```

**不要让 MCP 直接进入 Agent 核心逻辑。**

---

## 13. Activity Runtime

Chat 只是 Activity 的一种。Activity 让 Agent 从一次性聊天逐步发展到持续任务。

```text
Activity
├── ChatActivity
├── TaskActivity
├── ScheduledActivity
├── EventActivity
├── BackgroundActivity
└── AutonomousActivity
```

示例：

```text
每天 23:00
 ↓
DailyReviewActivity
 ↓
读取当天记录
 ↓
生成总结
 ↓
等待用户
```

未来可以：天气变化 → WeatherEvent → Activity → Agent → 通知用户。

---

## 14. Planner

第一版可以简单，但最终建议独立出来。Planner 不负责执行：

```text
Planner
├── Goal Parser
├── Task Decomposer
├── Plan
├── Replan
└── Validation
```

```text
Planner → Plan → Executor
```

示例：帮我安排三天旅行 → 确定地点 / 查询交通 / 查询酒店 / 查询天气 / 生成行程。

---

## 15. Permission / Approval / Security

### 15.1 Approval / Permission System

Agent 不能因为 LLM 说 `send_email()` 就直接发送：

```text
Agent
 ↓
Tool
 ↓
Risk Check
 ↓
Need Approval?
 ├── No → Execute
 └── Yes
       ↓
    User Confirm
       ↓
     Execute
```

风险等级：

```text
LOW    查询天气、搜索网页、计算
MEDIUM 修改日历、写文件、创建任务
HIGH   发送邮件、删除文件、修改重要数据、支付
```

### 15.2 Security Layer

```text
Authentication
Authorization
Secret Management
Sandbox
Tool Permission
Data Isolation
Audit
Rate Limit
Prompt Injection Defense
```

尤其引入 RAG + MCP + Browser 以后，必须防：

```text
Prompt Injection
Data Exfiltration
Malicious File
Tool Abuse
Privilege Escalation
```

---

## 16. Observability / Evaluation

### 16.1 Observability

Agent 比普通 Web 应用更需要可观测性。用 `trace_id` / `run_id` / `span_id` 串起一次 Agent Run：

```text
Trace
├── Request
├── Context
├── LLM Call
├── Token Usage
├── Tool Call
├── Tool Result
├── RAG Retrieval
├── Memory Retrieval
├── Skill
├── Error
└── Final Response
```

> **日志里不要无条件记录敏感信息、完整 Prompt 或用户隐私数据。**

### 16.2 Evaluation

回答"我的 Agent 到底有没有变聪明"：

```text
Evaluation
├── Chat Quality
├── Memory Recall
├── RAG Recall
├── Tool Selection
├── Tool Success
├── Hallucination
├── Safety
└── Regression Tests
```

固定测试集示例：

```text
用户：我上周说过我喜欢什么咖啡？
期待：准确召回 Memory
```

**每次修改 Agent 后自动测试。**

---

## 17. Model Gateway

不要让业务代码直接绑定某一家模型 API（禁止 `openai.chat(...)` 直连）：

```text
Model Gateway
├── Chat Model
├── Embedding Model
├── Reranker
├── Vision Model
├── STT
└── TTS
```

```text
Agent → Model Gateway → OpenAI / Anthropic / Gemini / Qwen / Local Model
```

以后换模型不会影响 Agent Runtime。推荐统一走 **OpenAI 兼容协议**（`base_url` + `api_key` 配置化），
一个 provider 实现即可切换 DeepSeek / Qwen / 智谱 / Ollama。

---

## 18. 数据与基础设施

### 18.1 MVP

```text
SQLite
```

足以支持第一版。**Redis 不是必需组件。**

### 18.2 演进

```text
PostgreSQL（单机增强）
  users / conversations / messages / agent_runs / memories /
  skills / tool_runs / activities / tasks / approvals / audit_logs

pgvector
  memory embeddings / document chunks / knowledge embeddings

Object Storage（S3 / MinIO）
  PDF / 图片 / 音频 / 视频 / 附件

Redis（有并发需求后，可选）
  Cache / Session / Rate Limit / Lock / Queue / PubSub

Queue / Worker（后台 Activity、定时任务、异步解析、主动提醒出现后再引入）
  Celery / Dramatiq / RQ / Arq
```

### 18.3 Event Bus / Job Queue

```text
API
 ↓
Create Activity
 ↓
Job Queue
 ↓
Worker
 ↓
Agent Runtime
```

MVP 可以不加。

---

## 19. Configuration / Feature Flags

```yaml
agent:
  max_steps: 10
  timeout: 120

memory:
  enabled: true

rag:
  enabled: true

tools:
  browser: false
```

这样可以逐步开启功能。

---

## 20. Prompt / Policy Management

Prompt 不要散落在代码里：

```text
prompts/
├── system/
├── memory/
├── rag/
├── planning/
├── tool/
└── skills/
```

同时版本化 `prompt_version`，这样才能知道"为什么昨天回答很好，今天突然变差"。

---

## 21. Plugin / Skill Registry

如果以后希望像 Alife 一样动态扩展：

```text
Registry
├── Skills
├── Tools
├── MCP Servers
└── Models
```

记录：`name / version / author / description / permissions / dependencies / enabled`。
最终可以发展成 Plugin Marketplace，但属于后期。

---

## 22. 推荐项目目录

```text
personal-ai/
│
├── apps/
│   ├── api/          FastAPI 路由、SSE、依赖注入
│   ├── worker/       Job Queue Worker（P5）
│   └── web/          Next.js + React + TypeScript（Chat / Memory / Knowledge / Skill Center / Activity）
│
├── core/
│   ├── agent/
│   │   ├── runtime/  Agent Loop
│   │   ├── state/    AgentRun / Message 状态
│   │   ├── planner/  （P6）
│   │   └── executor/ 执行器
│   ├── character/    Identity / Personality / User Profile
│   ├── context/      Context Engine + Token Budget
│   ├── activity/     Activity Runtime（P5）
│   ├── memory/       Extractor / Pipeline / Store
│   ├── rag/          Parser / Chunker / Retriever（P2）
│   ├── skills/       Skill 注册与调度
│   ├── tools/        Tool 定义与 Tool Router
│   ├── mcp/          MCP Client（P4）
│   ├── models/       Model Gateway
│   ├── permissions/  风险分级与 Approval
│   └── evaluation/   评估集与回归（P1 起）
│
├── infrastructure/
│   ├── database/     SQLAlchemy、连接管理、迁移
│   ├── vector_store/ pgvector（P2）
│   ├── object_storage/ 附件存储（P2）
│   ├── cache/        可选（P5）
│   ├── queue/        Job Queue（P5）
│   ├── observability/ trace、日志
│   └── config/       配置加载 + Feature Flags
│
├── prompts/
│   ├── system/  memory/  rag/  planning/  tool/  skills/
│
├── skills/
│   ├── daily-review/
│   ├── document-summary/
│   └── .../SKILL.md
│
├── tests/
│   ├── unit/  integration/  agent/  rag/  evaluation/
│
├── migrations/
├── docker/
└── README.md
```

---

## 23. 一次聊天的完整数据流

```text
User
 ↓
Client
 ↓
POST /chat
 ↓
Authentication
 ↓
Conversation Service
 ↓
Agent Runtime
 ↓
Load Character
 ↓
Load Activity State
 ↓
Context Engine
 │
 ├── Recent Messages
 ├── Summary
 ├── Memory Retrieval
 ├── RAG Retrieval
 ├── Active Skill
 └── Available Tools
 ↓
Model Gateway
 ↓
LLM
 ↓
Decision
 │
 ├── Direct Answer
 │
 ├── Skill → Tool → MCP
 │
 └── Plan → Execute → Observe → Replan → LLM
 ↓
Response
 ↓
Memory Extraction
 ↓
Persist
 ↓
SSE（Agent Event）→ Client
```

---

## 24. 开发路线（P0-P6）

| 阶段 | 范围 | 目标 |
|---|---|---|
| **P0 聊天 MVP** | Next.js + React + TypeScript、FastAPI、Model Gateway、Conversation / Message、Agent Runtime、基础 Context Engine、SSE、SQLite、Character / Identity | 先做出一个真正好用的聊天助手 |
| **P1 认识用户** | Long-term Memory、Memory UI、Conversation Summary、需要时迁移 PostgreSQL | 让 Agent 开始"认识你" |
| **P2 理解资料** | File Upload、RAG、pgvector、Knowledge UI、Citation | 让 Agent 开始"理解你的资料" |
| **P3 开始做事** | Skill、Tool Calling、Permission、Approval、Observability | 让 Agent 开始"帮你做事" |
| **P4 连接外部世界** | MCP、Web Search、Browser、Third-party APIs | 连接外部工具和服务 |
| **P5 主动工作** | Activity、Scheduler、Queue、Worker、Background Agent、Event Trigger | 让 Agent 持续、主动地工作 |
| **P6 高级 Agent** | Planner、Replanning、Autonomous Activity、Plugin Registry、Skill Marketplace、Advanced Evaluation | 成为真正的 Personal AI Operating System |

> 注：早期版本（分层架构版）的 P0-P3 四阶段与本路线对应关系：
> 旧 P1（记忆+RAG+Skill+Tool）≈ 新 P1+P2+P3；旧 P2（MCP+Activity）≈ 新 P4+P5；旧 P3 ≈ 新 P6。
> 新路线每个阶段交付物更小、更可验收，建议以 P0-P6 为准。

---

## 25. 第一版验收标准

```text
□ 用户可以创建、切换和删除 Conversation
□ 模型支持 SSE 流式输出
□ 一次 Agent Run 有 run_id 并可追踪
□ Context Engine 可以控制上下文长度
□ Character / System Prompt 与业务代码解耦
□ 用户可以查看和管理长期 Memory
□ 上传文件后可以建立 Knowledge，并在回答中提供来源
□ Tool / Skill 有统一接口
□ 高风险 Tool 可以触发 Approval
□ 前端不依赖具体 LLM 厂商
□ 增加 Agent Event 不需要重写前端聊天逻辑
```

---

## 26. 最终产品形态

```text
                    PERSONAL AI
                         │
        ┌────────────────┼────────────────┐
        │                │                │
      TALK             KNOW             ACT
        │                │                │
      Chat            Memory            Skill
      Voice             RAG             Tool
      Vision          Knowledge          MCP
        │                │                │
        └────────────────┼────────────────┘
                         │
                      ACTIVITY
                         │
              ┌──────────┼──────────┐
              ↓          ↓          ↓
            Task      Schedule    Event
              │          │          │
              └──────────┼──────────┘
                         ↓
                    AGENT RUNTIME
                         │
                    PERSONAL AI
```

---

## 27. 最容易漏掉的东西

除 RAG / Memory / Skill / MCP 之外，建议额外加入：

| # | 模块 | 解决什么问题 |
|---|---|---|
| ① | Activity Runtime | Agent 不只是聊天，还能持续执行任务 |
| ② | Context Engine | 到底把什么信息给 LLM |
| ③ | Permission / Approval | Agent 能不能执行这个动作 |
| ④ | Event / Job Queue | 定时任务和后台任务怎么运行 |
| ⑤ | Model Gateway | 换模型不用重写 Agent |
| ⑥ | Observability | Agent 为什么这么做、哪里出错 |
| ⑦ | Evaluation | 修改后到底有没有变好 |
| ⑧ | Prompt / Policy Versioning | Agent 行为为什么发生变化 |
| ⑨ | Object Storage | PDF、图片、音频等附件放在哪里 |
| ⑩ | Security / Sandbox | Browser、Code、File、MCP 这些高权限工具如何安全运行 |

其中 **Context Engine、Permission、Model Gateway 必须在 P0 就位**，否则后期返工成本高。

---

## 28. 架构原则

```text
1.  先确定业务边界，再选择具体技术。
2.  Chat 是入口，不是整个系统。
3.  Conversation 与 Memory 分离。
4.  Memory 与 RAG 分离。
5.  Skill、Tool、MCP 分层。
6.  Agent Runtime 统一编排。
7.  前后端通过 Agent Event Protocol 解耦。
8.  高风险 Tool 必须经过 Permission / Approval。
9.  Redis 不是必须组件。
10. MVP 优先保证聊天质量、稳定性和可演进性，不追求组件数量。
```

最重要的不是 LangGraph / PostgreSQL / Redis，而是以下抽象边界：

```text
Character
    ↓
Agent Runtime
    ↓
Context
    ↓
Memory / RAG
    ↓
LLM
    ↓
Skill
    ↓
Tool
    ↓
MCP
    ↓
External World
```

以及 Activity、Permission、Observability、Evaluation。这些边界确定后，底层技术都可以替换。
