# Personal AI Agent：分层架构设计与完整功能规划

> 目标：设计一个参考 Alife、Personal AI、现代 Agent Runtime 思路的个人 AI Assistant。
>
> 核心定位：**一个长期存在、能聊天、记忆用户、检索知识、使用 Skill / Tool / MCP，并逐步具备主动活动能力的 Personal AI。**
>
> 本文重点不是绑定某一个框架，而是先把**模块边界、数据流、职责和演进路线**确定下来。数据库、LLM、Agent 框架都可以替换。

---

## 1. 最终架构总览

建议最终采用下面的分层：

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
│ Skill / Tool / Summary  │   │ Background / Autonomous         │
└────────────┬───────────┘   └─────────────────────────────────┘
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
               │                               │
               ▼                               ▼
       Native Tool Runtime                  MCP Layer
       Search / File / Code                 MCP Client
       Calculator / etc.                    MCP Servers
               │                               │
               └───────────────┬───────────────┘
                               ▼
                     External World / Services

┌──────────────────────────────────────────────────────────────┐
│                         Data Layer                           │
│ SQL / Vector / Object Storage / Cache / Event Store          │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                  Cross-Cutting Infrastructure                 │
│ Security / Permission / Observability / Audit / Cost /      │
│ Rate Limit / Secrets / Config / Feature Flags                │
└──────────────────────────────────────────────────────────────┘
```

---

# 2. 第一层：Client Layer

## 职责

负责用户和 Agent 的交互，不负责 Agent 决策。

### 第一版

建议：

```text
Web
├── Chat
├── Conversation List
├── Settings
├── Memory Management
└── Knowledge Files
```

### 后期

```text
Web
Mobile
Desktop
Voice
Browser Extension
```

## Chat UI 必须支持

- 流式输出
- Markdown
- 代码高亮
- 文件上传
- 图片上传
- 消息重新生成
- 停止生成
- 重试
- 编辑用户消息
- 引用/来源
- Tool 执行状态
- Agent 思考状态（只展示安全、可解释的状态，不暴露内部隐藏推理）
- Tool 调用结果摘要
- 用户确认卡片

## 不应该放在前端

不要让前端决定：

```text
应该调用哪个 Tool
应该读取哪些 Memory
应该执行哪个 Skill
是否允许执行危险操作
```

这些必须由后端控制。

---

# 3. 第二层：API Layer

推荐：

```text
FastAPI
```

API 层负责：

```text
POST /chat
GET  /conversations
POST /files
GET  /memories
POST /memories
DELETE /memories/:id
GET  /skills
GET  /tools
POST /approval
```

流式聊天建议：

```text
SSE
```

如果以后需要服务端主动推送、实时状态同步，再考虑：

```text
WebSocket
```

---

# 4. 第三层：Character / Identity Layer

这是参考 Alife 后建议增加的重要层。

不要把 Agent 设计成：

```text
LLM + Prompt
```

而是：

```text
Character
├── Identity
├── Personality
├── User Profile
├── Preferences
├── Goals
└── Relationship State
```

## Identity

例如：

```yaml
name: Assistant
role: Personal AI Assistant
language: zh-CN
```

## Personality

例如：

```text
语气
回答长度
幽默程度
正式程度
主动程度
```

## User Profile

保存：

```text
用户偏好
语言
时区
常用设置
用户明确要求记住的信息
```

注意：

**敏感信息必须有明确的存储和权限策略，不应该因为“记忆功能”自动永久保存。**

---

# 5. 第四层：Agent Runtime

这是整个系统的核心。

建议把 Agent Runtime 独立出来：

```text
Agent Runtime
├── Agent Loop
├── State
├── Planner
├── Executor
├── Interrupt
├── Approval
├── Retry
├── Timeout
└── Cancellation
```

核心循环：

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
Answer    Tool / Skill
             ↓
          Execute
             ↓
        Observation
             ↓
          Update State
             ↓
             LLM
```

## 不建议

第一版不要直接做“无限自主 Agent”。

应该限制：

```text
max_steps
timeout
tool permission
budget
retry count
```

---

# 6. 第五层：Context Engine

这是项目中最值得独立成模块的一层。

不要直接：

```python
messages = all_history
```

而是：

```text
Context Engine
├── System Context
├── Recent Conversation
├── Conversation Summary
├── User Memory
├── RAG Results
├── Active Skill
├── Available Tools
├── Tool Results
└── Current Task State
```

最终：

```text
Context
    ↓
Context Policy
    ↓
Token Budget
    ↓
LLM
```

## Context Builder

建议接口：

```python
context = context_engine.build(
    user_id=user_id,
    conversation_id=conversation_id,
    message=user_message,
    task_state=task_state,
)
```

---

# 7. 第六层：Memory System

Memory 不应该等同于聊天记录。

建议拆成：

```text
Memory
├── Working Memory
├── Episodic Memory
├── Semantic Memory
├── User Profile
└── Conversation Summary
```

## Working Memory

当前任务状态：

```text
用户正在做什么
当前计划是什么
已经完成了什么
下一步是什么
```

## Episodic Memory

发生过的事情：

```text
2026-08-10
用户讨论过换工作
```

## Semantic Memory

长期事实：

```text
用户喜欢简洁回答
用户常用中文
```

## Memory Pipeline

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

不要把每句话都存进长期记忆。

---

# 8. 第七层：RAG / Knowledge Layer

RAG 建议独立于 Memory。

```text
Knowledge
├── File Ingestion
├── Parser
├── Chunker
├── Embedding
├── Vector Store
├── Metadata
├── Retriever
└── Reranker
```

数据流：

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

查询：

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

## Memory 和 RAG 的区别

```text
Memory
= 关于用户和过去经历的知识

RAG
= 外部资料/用户资料中的知识
```

两者可以共享向量基础设施，但业务逻辑必须分开。

---

# 9. 第八层：Skill System

Skill 是：

> “如何完成某一类事情。”

建议：

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

例如：

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

Skill 不应该直接操作数据库或第三方 API。

它应该：

```text
Skill
 ↓
Tool
 ↓
Tool Router
 ↓
MCP / Native Tool
```

---

# 10. 第九层：Tool Layer

Tool 是 Agent 实际执行动作的接口。

例如：

```text
Native Tools
├── calculator
├── file_read
├── file_write
├── web_search
├── time
└── weather

External Tools
├── Gmail
├── Calendar
├── Notion
└── GitHub
```

每个 Tool 应该定义：

```text
name
description
input_schema
output_schema
permission
timeout
risk_level
```

---

# 11. 第十层：MCP Layer

MCP 是外部工具/资源的标准连接层。

建议：

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

架构：

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

不要让 MCP 直接进入 Agent 核心逻辑。

---

# 12. 第十一层：Activity Runtime

这是参考 Alife 后，我建议你一定增加的一层。

Chat 只是 Activity 的一种。

```text
Activity
├── ChatActivity
├── TaskActivity
├── ScheduledActivity
├── EventActivity
├── BackgroundActivity
└── AutonomousActivity
```

例如：

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

未来可以：

```text
天气变化
 ↓
WeatherEvent
 ↓
Activity
 ↓
Agent
 ↓
通知用户
```

---

# 13. 第十二层：Planner

第一版可以简单，但最终建议独立出来。

```text
Planner
├── Goal Parser
├── Task Decomposer
├── Plan
├── Replan
└── Validation
```

例如：

```text
用户：
帮我安排一次三天旅行

Goal
 ↓
Plan
 ├── 确定地点
 ├── 查询交通
 ├── 查询酒店
 ├── 查询天气
 └── 生成行程
```

Planner 不应该负责执行。

```text
Planner
 ↓
Plan
 ↓
Executor
```

---

# 14. 第十三层：Approval / Permission System

这是之前架构里容易漏掉，但真正上线必须有的。

Agent 不能因为 LLM 说：

```text
send_email()
```

就直接发送。

应该：

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

建议风险等级：

```text
LOW
├── 查询天气
├── 搜索网页

MEDIUM
├── 修改日历
├── 写文件
├── 创建任务

HIGH
├── 发送邮件
├── 删除文件
├── 修改重要数据
├── 支付
```

---

# 15. 第十四层：Security Layer

最终一定需要：

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

尤其 RAG + MCP + Browser 以后，必须防：

```text
Prompt Injection
Data Exfiltration
Malicious File
Tool Abuse
Privilege Escalation
```

---

# 16. 第十五层：Observability

Agent 比普通 Web 应用更需要可观测性。

建议记录：

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

但要注意：

**日志里不要无条件记录敏感信息、完整 Prompt 或用户隐私数据。**

可以采用：

```text
trace_id
run_id
span_id
```

串起一次 Agent Run。

---

# 17. 第十六层：Model Gateway

不要让业务代码直接：

```python
openai.chat(...)
```

建议：

```text
Model Gateway
├── Chat Model
├── Embedding Model
├── Reranker
├── Vision Model
├── STT
└── TTS
```

例如：

```text
Agent
 ↓
Model Gateway
 ├── OpenAI
 ├── Anthropic
 ├── Gemini
 ├── Qwen
 └── Local Model
```

以后换模型不会影响 Agent Runtime。

---

# 18. 第十七层：Storage Layer

第一版不需要一口气上很多数据库。

推荐演进：

### MVP

```text
SQLite
```

### 单机增强

```text
PostgreSQL
+
pgvector
```

### 有并发需求

```text
PostgreSQL
+
pgvector
+
Redis
```

## PostgreSQL

保存：

```text
users
conversations
messages
activities
tasks
memories
skills
tool_runs
approvals
audit_logs
```

## pgvector

保存：

```text
memory embeddings
document chunks
knowledge embeddings
```

## Object Storage

保存：

```text
PDF
Images
Audio
Videos
Attachments
```

可以使用：

```text
S3 / MinIO
```

## Redis

不是必须。

未来用于：

```text
Cache
Session
Rate Limit
Distributed Lock
Task Queue
Pub/Sub
```

---

# 19. 第十八层：Event Bus / Job Queue

这是原先架构中容易漏掉的东西。

如果最终支持：

```text
定时任务
后台 Activity
主动提醒
异步 RAG
文件解析
邮件处理
```

就需要异步任务系统。

架构：

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

以后可以使用：

```text
Celery / Dramatiq / RQ / Arq
```

或者根据整体架构选择其他方案。

---

# 20. 第十九层：Configuration / Feature Flags

建议单独设计：

```text
Config
├── Model Config
├── Agent Config
├── Memory Config
├── RAG Config
├── Tool Config
└── Feature Flags
```

例如：

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

# 21. 第二十层：Evaluation

这是很多 Agent 项目最容易漏掉的一层。

你需要能够回答：

> “我的 Agent 到底有没有变聪明？”

建议建立：

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

例如固定测试集：

```text
用户：
我上周说过我喜欢什么咖啡？

期待：
准确召回 Memory
```

每次修改 Agent 后自动测试。

---

# 22. 第二十一层：Prompt / Policy Management

Prompt 不要散落在代码里。

建议：

```text
prompts/
├── system/
├── memory/
├── rag/
├── planning/
├── tool/
└── skills/
```

同时版本化：

```text
prompt_version
```

这样才能知道：

```text
为什么昨天回答很好，
今天突然变差？
```

---

# 23. 第二十二层：Plugin / Skill Registry

如果以后希望像 Alife 一样动态扩展：

```text
Registry
├── Skills
├── Tools
├── MCP Servers
└── Models
```

可以记录：

```text
name
version
author
description
permissions
dependencies
enabled
```

最终可以发展成：

```text
Plugin Marketplace
```

但这属于后期。

---

# 24. 推荐的代码目录

如果使用 Python + FastAPI，我建议最终目录接近：

```text
personal-ai/
│
├── apps/
│   ├── api/
│   ├── worker/
│   └── web/
│
├── core/
│   ├── agent/
│   │   ├── runtime/
│   │   ├── state/
│   │   ├── planner/
│   │   └── executor/
│   │
│   ├── character/
│   ├── context/
│   ├── activity/
│   ├── memory/
│   ├── rag/
│   ├── skills/
│   ├── tools/
│   ├── mcp/
│   ├── models/
│   ├── permissions/
│   └── evaluation/
│
├── infrastructure/
│   ├── database/
│   ├── vector_store/
│   ├── object_storage/
│   ├── cache/
│   ├── queue/
│   └── observability/
│
├── prompts/
│
├── skills/
│   ├── daily-review/
│   ├── document-summary/
│   └── ...
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── agent/
│   ├── rag/
│   └── evaluation/
│
├── migrations/
│
├── docker/
│
└── README.md
```

---

# 25. 一次聊天到底怎么走？

最终完整数据流：

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
 ├── Skill
 │      ↓
 │    Tool
 │      ↓
 │    MCP
 │
 └── Plan
        ↓
      Execute
        ↓
      Observe
        ↓
      Replan
        ↓
       LLM
 ↓
Response
 ↓
Memory Extraction
 ↓
Persist
 ↓
SSE → Client
```

---

# 26. 最终完整架构图

```text
                              USER
                                │
                                ▼
                    ┌─────────────────────┐
                    │     Client Layer    │
                    │ Web / Mobile / App  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │      API Layer      │
                    │ Auth / Chat / File  │
                    └──────────┬──────────┘
                               │
                               ▼
              ┌───────────────────────────────────┐
              │        PERSONAL AI CHARACTER       │
              │ Identity / Personality / Profile  │
              └────────────────┬──────────────────┘
                               │
                               ▼
              ┌───────────────────────────────────┐
              │          AGENT RUNTIME             │
              │ Loop / State / Planner / Executor │
              └───────────────┬───────────────────┘
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
       Context Engine      Activity          Planner
             │              Runtime             │
             │                │                 │
     ┌───────┼────────┐      │                 │
     ▼       ▼        ▼      ▼                 ▼
  Recent  Memory     RAG   Chat/Task          Plan
    │       │         │    Scheduled           │
    │       │         │    Background           │
    └───────┴─────────┴────────┬────────────────┘
                               ▼
                       ┌───────────────┐
                       │ Model Gateway │
                       │ LLM/Embed/VLM │
                       └───────┬───────┘
                               │
                               ▼
                       ┌───────────────┐
                       │ Skill Router  │
                       └───────┬───────┘
                               │
                               ▼
                       ┌───────────────┐
                       │ Tool Router   │
                       └───────┬───────┘
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
              Native Tools              MCP
                    │                     │
                    └──────────┬──────────┘
                               ▼
                       External Services


        ┌─────────────────────────────────────────────────┐
        │                 DATA LAYER                       │
        │ SQL / Vector / Object Storage / Cache / Queue   │
        └─────────────────────────────────────────────────┘

        ┌─────────────────────────────────────────────────┐
        │             CROSS-CUTTING SYSTEMS                │
        │ Security / Permission / Audit / Observability   │
        │ Evaluation / Prompt Versioning / Config         │
        └─────────────────────────────────────────────────┘
```

---

# 27. 哪些东西是 MVP，哪些以后再做？

## P0：第一版必须

```text
Chat
FastAPI
LLM Gateway
Conversation
Character / Identity
Context Engine
基本 Memory
SSE
SQLite
```

目标：

> **先做出一个真正好用的聊天助手。**

---

## P1：第二阶段

```text
Long-term Memory
RAG
File Upload
pgvector
Skill
Tool Calling
Permission
Observability
```

目标：

> **让 Agent 开始“认识你”和“使用你的资料”。**

---

## P2：第三阶段

```text
MCP
Activity
Task
Scheduler
Background Worker
Web Search
Browser
Voice
Vision
```

目标：

> **让 Agent 开始真正帮你做事。**

---

## P3：第四阶段

```text
Autonomous Activity
Planner
Replanning
Plugin Registry
Skill Marketplace
Multi-Agent
Advanced Evaluation
```

目标：

> **让它成为真正的 Personal AI Operating System。**

---

# 28. 当前架构里最容易漏掉的东西

除了你之前提出的：

```text
RAG
Memory
Skill
MCP
```

我建议额外加入：

### ① Activity Runtime

解决：

> Agent 不只是聊天，还能持续执行任务。

### ② Context Engine

解决：

> 到底把什么信息给 LLM。

### ③ Permission / Approval

解决：

> Agent 能不能执行这个动作。

### ④ Event / Job Queue

解决：

> 定时任务和后台任务怎么运行。

### ⑤ Model Gateway

解决：

> 换模型不用重写 Agent。

### ⑥ Observability

解决：

> Agent 为什么这么做、哪里出错。

### ⑦ Evaluation

解决：

> 修改后到底有没有变好。

### ⑧ Prompt / Policy Versioning

解决：

> Agent 行为为什么发生变化。

### ⑨ Object Storage

解决：

> PDF、图片、音频等附件放在哪里。

### ⑩ Security / Sandbox

解决：

> Browser、Code、File、MCP 这些高权限工具如何安全运行。

---

# 29. 最终设计原则

这个项目最重要的不是：

```text
LangGraph
PostgreSQL
Redis
```

而是以下几个**抽象边界**：

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

以及：

```text
Activity
Permission
Observability
Evaluation
```

这几个边界确定后，底层技术都可以替换。

---

# 30. 最终产品形态

如果按照这套架构继续发展，你最后得到的不是一个简单 ChatBot，而是：

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

**核心理念：**

> Chat 是入口，不是整个系统。
>
> Memory 是“记住你”。
>
> RAG 是“知道你的资料”。
>
> Skill 是“知道怎么做一类事情”。
>
> Tool 是“具体执行动作”。
>
> MCP 是“连接外部世界”。
>
> Activity 是“持续做事情”。
>
> Agent Runtime 是“把这些东西组织起来的大脑”。
>
> Character 是“这个 AI 本身”。

