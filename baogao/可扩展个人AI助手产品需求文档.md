# 可扩展个人 AI 助手产品需求文档

> 项目：Personal AI Agent
> 项目路径：`E:\Pycharm\JQ\personal-ai`
> 文档版本：PRD v1.0
> 编写日期：2026-08-21
> 文档状态：开发基线草案
> 后续开发原则：需求确认后再进入代码实现

---

## 1. 产品定义

### 1.1 一句话定义

一个面向普通用户的可扩展个人 AI 助手：默认提供稳定的角色化聊天、上下文、长期记忆和个人资料理解能力；用户可以通过可视化能力中心，按需安装、配置、启用、关闭和卸载音乐、图片、日历、编码等能力。

### 1.2 产品愿景

```text
基础状态：它是一个了解用户、角色稳定、可以长期交流的 AI 助手。

扩展之后：它可以根据用户选择，获得控制音乐、生成图片、管理日历、
处理资料、执行编码或连接其他软件的能力。

关闭能力：对应功能立即从新任务中消失，不影响基础聊天和其他能力。
```

产品借鉴“最小 Agent 内核 + 按需扩展”的思想，但面向普通用户而不是开发者：用户看到的是“音乐”“图片生成”“编码”等能力卡片，而不是 MCP、Tool Schema、Prompt 文件或代码模块。

### 1.3 核心价值

1. **稳定的基础助手**：不安装任何插件也能完成高质量长期对话。
2. **真正了解用户**：区分用户记忆和个人资料库，按需召回，不乱引用。
3. **角色可设计**：通过设置界面调整身份、性格、语言和主动程度。
4. **能力可组合**：同一个助手可以安装多个互相隔离的能力。
5. **能力可撤销**：用户随时关闭或卸载，不留下隐式执行入口。
6. **普通用户可理解**：安装、授权、执行和失败提示不暴露底层技术细节。
7. **安全可观察**：外部动作有权限、审批、预算、状态和历史记录。

---

## 2. 当前基础与改造目标

### 2.1 当前已具备

项目 P0–P6 已提供：

- FastAPI + SSE 流式聊天；
- Conversation、Message、AgentRun 持久化；
- Character、Memory、Summary、Context Token Budget；
- PDF、DOCX、TXT、Markdown 个人知识库；
- Vector + BM25 + RRF、RAG 门控、引用白名单；
- Tool、Skill、审批、ToolRun；
- stdio MCP Client；
- Activity 调度与恢复；
- direct/planned、Plan、PlanStep 和一次 Replan；
- Capability 只读页面；
- 后端、RAG、Planner 与前端验证基线。

### 2.2 当前不满足的部分

| 当前状态 | 目标状态 |
|---|---|
| Character 主要由 YAML 配置 | 可视化 Assistant Profile |
| Tool 是全局静态注册 | 按助手、按 Run 生成能力快照 |
| Skill 启动时加载 | 插件启停后动态生效 |
| MCP 启动时连接 | 插件配置后连接、禁用后关闭 |
| Capability Registry 只读 | 可安装、配置、启用、禁用、卸载 |
| 用户直接看到 Skill/MCP 等概念 | 普通用户看到业务能力卡片 |
| Planner 是主界面显式模式 | 作为可选高级能力或自动编排策略 |
| 角色、资料、能力边界未统一 | Assistant Profile 成为统一装配入口 |
| 无插件生命周期和版本管理 | 有状态、版本、兼容性和失败恢复 |

### 2.3 改造原则

- 不推倒现有 Chat、Memory、RAG、Tool、MCP 和 Planner；
- 先建立稳定能力运行时，再开发具体插件；
- 现有功能逐步通过统一 Registry 接入，不一次性大重构；
- 所有旧请求默认行为保持兼容；
- 关闭所有非基础能力后，基础聊天必须完全正常。

---

## 3. 目标用户与核心场景

### 3.1 目标用户

- 想拥有长期个人 AI 助手的普通用户；
- 不理解 MCP、Tool Calling 或 Prompt Engineering；
- 希望根据自身需求安装少量能力；
- 重视隐私、可控性和可撤销性；
- 未来可能需要把助手扩展为生活、学习、创作或编码助手。

### 3.2 核心场景

#### 场景 A：基础聊天

用户未启用任何扩展能力，与助手长期对话。助手保持角色一致，合理使用最近消息、摘要和记忆，不因为没有插件而报错。

#### 场景 B：角色设定

用户在“助手设置”中选择：

```text
名称：小派
身份：个人生活与学习助手
风格：温和、简洁、直接
回复长度：短
主动程度：适中
称呼：称呼用户为“你”
```

保存后，新对话立即使用新设定；历史消息内容不被修改。

#### 场景 C：了解用户

用户说“我不吃花生”，助手可在用户授权和策略允许时保存为长期记忆。之后询问食谱时主动规避花生。用户可以查看、修改、禁用或删除这条记忆。

#### 场景 D：理解个人资料

用户上传简历、笔记或项目文档。只有资料相关问题才检索，回答实际使用资料时显示来源；计算、问候、时间等无关任务不附带资料卡片。

#### 场景 E：安装音乐能力

用户从能力中心安装音乐插件，完成账号授权并启用。助手获得搜索、播放、暂停和切换歌曲能力。关闭后，新 Run 不再看到音乐 Skill 和 Tool。

#### 场景 F：安装图片生成能力

用户安装图片插件，选择模型/服务并配置额度。助手可以调用 `generate_image`。关闭后只能提供文字创意，不能实际生成图片。

#### 场景 G：安装编码能力

用户安装高风险编码插件，选择允许访问的目录并确认命令执行权限。助手可以读写代码、执行测试和使用 Git。插件关闭后不能继续访问相关目录或命令。

#### 场景 H：能力缺失

用户要求“播放音乐”，但未安装音乐能力。助手说明当前未启用，并提供前往能力中心的入口；不能伪装已经播放。

#### 场景 I：从网上搜索并安装 Skill

用户在能力中心搜索“旅行规划”“Spotify”“图片生成”或“Python 编码”。系统从在线能力目录返回 Skill/Package，展示作者、版本、权限、依赖和风险。用户安装并启用后，Agent 可以按需加载该 Skill；关闭后，新 Run 不再使用。

#### 场景 J：用户自己创建 Skill

用户通过可视化编辑器或自然语言描述创建 Skill，例如“帮我设计一个每周学习复盘 Skill”。系统生成草稿，展示说明、触发场景、依赖工具和示例。用户审核、测试并启用后，该 Skill 才能进入 Agent 上下文。

---

## 4. 产品信息架构

### 4.1 普通用户导航

```text
对话
我的助手
我的资料
能力中心
任务
设置
```

### 4.2 页面职责

| 页面 | 主要内容 |
|---|---|
| 对话 | 消息、来源、动作结果、必要的审批和可折叠计划 |
| 我的助手 | 名称、头像、角色、性格、语言、回复偏好 |
| 我的资料 | Memory、上传文件、资料状态、数据删除 |
| 能力中心 | 在线搜索、已安装、自定义创建、配置、启停、权限和健康状态 |
| 任务 | 提醒、周期任务、执行历史 |
| 设置 | 模型、隐私、数据、通知和高级设置 |

### 4.3 高级设置

MCP、Tool、Skill、运行诊断、Capability ID、Provider 原始配置等只出现在高级设置中，默认不向普通用户展示。

---

## 5. 基础助手需求

## 5.1 Assistant Profile

### 功能字段

```text
名称
头像
身份描述
性格描述
说话风格
默认语言
回复长度：短 / 适中 / 详细
主动程度：被动 / 适中 / 主动
对用户的称呼
自定义规则
默认模型
记忆开关
资料库开关
已启用能力集合
```

### 行为要求

- 用户可预览角色设定效果；
- 保存后仅影响之后的模型调用；
- 自定义规则有长度限制；
- 角色设定不能覆盖平台安全规则；
- Plugin 不能修改角色设定；
- Assistant Profile 不存 API Key；
- v1 默认只提供一个助手，数据模型为未来多助手预留 `assistant_id`。

## 5.2 基础聊天

关闭所有可选能力时必须满足：

```text
正常流式回答
可以停止生成
会话可创建、重命名、删除
同一会话只有一个 running Run
长对话不会无限增长上下文
模型失败不会删除用户消息
后处理失败不影响已完成回答
角色设定保持稳定
无能力时不会生成虚假动作结果
```

### 基础聊天不包括

- 联网搜索；
- 音乐控制；
- 图片生成；
- 日历操作；
- 任意文件系统访问；
- 命令执行；
- 自主创建后台任务。

这些均由能力包提供。

## 5.3 Context Engine

默认上下文组装顺序：

```text
平台安全规则
→ Assistant Profile
→ 当前已启用 Skill 摘要
→ 相关用户记忆
→ 按需检索的个人资料
→ 会话摘要
→ 最近消息
→ 当前用户消息
```

要求：

- 所有区域有独立 token 预算；
- 总上下文不得超过模型限制；
- Plugin 只能通过受控 Hook 注入上下文；
- Plugin 注入内容被视为不可信资料，不能覆盖安全规则；
- 记录注入了哪些模块，不记录隐藏推理；
- 上下文构建失败时允许降级为基础聊天。

## 5.4 Memory

Memory 保存简短、稳定、可管理的用户信息：

```text
偏好
习惯
长期目标
个人资料
重要约束
正在进行的事项
```

要求：

- 自动提取必须满足重要性、置信度和敏感信息规则；
- 支持手动添加、编辑、禁用、删除；
- 新记忆与旧记忆冲突时不能静默覆盖；
- 用户纠正优先于模型提取；
- 禁止保存密码、Token、完整身份证号等敏感内容；
- Plugin 默认不能读取全部 Memory；
- 对外部服务发送 Memory 必须有权限说明。

## 5.5 个人资料库与 RAG

RAG 保存和检索大段个人资料，不替代 Memory。

要求：

- 支持 PDF、DOCX、TXT、Markdown；
- 文件使用安全 UUID 存储；
- 文档解析、分块、Embedding 和索引状态可见；
- 自动模式跳过明确无资料需求的问题；
- 支持 `自动 / 使用资料 / 不使用资料` 三态；
- 低相关结果不得注入；
- 检索候选不等于回答来源；
- 只保存和展示正文实际使用的 `[cN]`；
- 未知引用不能生成来源卡片；
- 文档删除后历史引用显示“资料已删除”；
- 资料中的 Prompt Injection 不得成为系统指令。

---

## 6. 能力系统概念

## 6.1 Skill

Skill 是模型可按需读取的说明和工作流程。

Skill 可以：

- 说明何时使用某能力；
- 说明参数收集流程；
- 说明失败处理方式；
- 绑定需要的 Tool 名称；
- 提供示例。

Skill 不可以：

- 自己执行外部动作；
- 创建新的 Tool；
- 扩大工具白名单；
- 绕过审批；
- 修改 Assistant Profile；
- 修改自身权限。

## 6.2 Tool

Tool 是可执行动作，必须具备：

```text
唯一名称
用户可理解的描述
JSON 参数 Schema
固定风险等级
来源插件
执行超时
结果大小限制
结构化 UI 摘要
审计记录
```

Tool 只能在所属插件已启用、当前 Assistant 已授权、Run 快照包含该能力时执行。

## 6.3 MCP

MCP 是外部服务连接方式之一。

要求：

- MCP Server 必须属于某个已安装 Plugin；
- 配置和 command 不进入模型上下文；
- 启用前进行连接测试和工具发现；
- 发现的工具需映射到插件声明的允许列表；
- 插件禁用后关闭连接或从可调用 Registry 中移除；
- MCP 故障不能导致基础聊天失败；
- MCP 高风险动作仍经过平台审批。

## 6.4 Plugin

Plugin 是普通用户实际管理的能力单元，可打包：

```text
Manifest
Skill
Tool Adapter
MCP 配置模板
Provider 配置
权限声明
通用设置 Schema
结果展示 Schema
帮助与隐私说明
```

v1 不允许插件随意向主应用注入任意前端 JavaScript；插件设置和结果优先由 JSON Schema 驱动的通用 UI 渲染。

## 6.5 Skill、MCP、Plugin 的用户界面模型

本项目不把三类内容混成一个抽象的“能力包”。设置界面像参考截图一样分别提供：

```text
技能（Skill）
MCP 服务器
插件（Plugin）
```

三者含义如下：

| 页面 | 用户在这里管理什么 | 首期是否开发 |
|---|---|---|
| 技能 | Agent 的任务说明和工作流程，可搜索、导入、新建、开关 | 是，首期重点 |
| MCP 服务器 | 连接外部工具或服务的服务器配置 | 后续 |
| 插件 | 将 Skill、MCP、Tool、配置和界面组合起来的完整扩展 | 后续 |

用户可以直接管理 Skill，不要求先创建 Plugin。只有一个扩展确实包含多个组件时，才需要 Plugin。

## 6.6 首期 Skill 模型：目录即安装

首期采用最简单、最容易验证的模型：

```text
把一个 Skill 文件夹放进 personal-ai/skills/
→ 系统重新扫描
→ Skill 出现在“设置 → 技能”列表
→ 用户打开开关
→ 新的对话 Run 可以使用该 Skill
```

标准目录示例：

```text
personal-ai/
└── skills/
    ├── time-helper/
    │   └── SKILL.md
    ├── calculator-helper/
    │   └── SKILL.md
    └── writing-helper/
        ├── SKILL.md
        └── references/          # 可选
```

最小 `SKILL.md`：

```markdown
---
name: writing-helper
description: 帮助用户改写、润色和调整文本语气
required_tools: []
---
当用户要求润色或改写时，保留原意，根据用户指定的语气输出。
```

对不需要新动作的 Skill，加入文件夹后不需要修改 Python 代码。若 Skill 声明已有 Tool，系统在 Tool 存在时允许启用；若依赖不存在，则仍显示在列表中，但标记“缺少依赖”并禁止启用。

Skill 的启用状态不直接改写下载来的 `SKILL.md`，而是保存在应用数据库中，并允许按 Assistant 分别启用。这样同一 Skill 可以给不同角色做不同选择，也不会在更新 Skill 时丢失开关状态。

系统启动时扫描一次；“刷新”按钮可在不重启服务的情况下重新扫描。扫描结果必须同时包含已启用、已禁用和缺少依赖的 Skill，不能像当前加载器一样直接隐藏禁用项。

## 6.7 技能设置页面

界面结构参考用户提供的截图，首期只保留必要元素：

```text
标题：技能
Assistant 选择器
搜索框
已安装数量
刷新按钮
导入按钮
新建按钮

内置
  Skill 名称 / 描述 / 状态 / 开关

本地导入
  Skill 名称 / 描述 / 来源 / 状态 / 开关 / 删除
```

每一项必须展示：

- 名称和中文描述；
- 来源：内置、本地导入、在线下载；
- 所需 Tool；
- 当前状态：可用、已关闭、缺少依赖、格式错误；
- 启用/禁用开关；
- 查看 `SKILL.md` 详情；
- 本地导入项可删除，内置项不可删除。

开关只影响之后创建的新 Run；进行中的 Run 使用启动时的能力快照，避免执行中途发生变化。

## 6.8 首批内置 Skill

首批只选择不需要账号、不需要 OAuth、不依赖收费外部服务、结果容易判断的能力：

| Skill | 作用 | 依赖 | 测试示例 |
|---|---|---|---|
| time-helper | 查询当前日期和时间 | `get_time` | “现在几点？” |
| calculator-helper | 安全计算基础算式 | `calculate` | “计算 122+22” |
| writing-helper | 改写、润色和调整语气 | 无 | “把这句话写得正式一些” |
| summarize-helper | 总结文本并提取要点 | 无 | “把这段话总结为三点” |
| translate-helper | 中英文翻译并保持格式 | 无 | “把这段中文翻译成英文” |
| file-notes | 读取和保存本地文本笔记 | `read_file`、`write_file` | “把这句话保存到笔记” |

`mcp-demo` 只作为 MCP 页面的技术测试，不算普通用户首批 Skill。图片生成、音乐控制、浏览器自动化和编码能力暂不作为首批验收项；以后需要时再通过 Tool、MCP 或 Plugin 增加。

## 6.9 从网上获取新的 Skill

首期不先建设复杂的应用市场。用户可以在浏览器、Git 仓库或其他 Skill 网站找到一个 Skill，然后使用以下任一方式加入：

```text
方式 A：把下载的 Skill 文件夹复制到 personal-ai/skills/
方式 B：在“技能”页面导入本地文件夹或 ZIP
```

导入成功后，后端把它复制到受控的 `skills/<slug>/` 目录，校验后刷新索引，它就成为列表中的一个新选项。ZIP 必须防止路径穿越，不能覆盖同名 Skill，不能把文件写到 `skills/` 以外。

第二阶段再增加：

```text
方式 C：输入 Git/URL，系统下载并导入
方式 D：在在线 Skill 目录中搜索并一键安装
```

在线安装本质上仍然是“下载 Skill 文件夹 → 校验 → 放入 skills 目录 → 刷新 → 用户选择启用”，不是运行时自动改写项目业务代码。

纯 Markdown、模板和静态参考资料可以按普通 Skill 导入。若下载内容带 Python/JavaScript、安装脚本、CLI 命令或未知 MCP 配置，则不能当作普通 Skill 直接执行，必须提示它属于高级扩展，并转入 MCP 或 Plugin 流程。

## 6.10 自己创建 Skill

“新建”页面首期只需要一个简单表单：

```text
名称
描述
什么时候使用
具体执行说明
示例请求
需要的已有 Tool（可选）
```

保存后生成 `skills/<slug>/SKILL.md`，先标记为草稿；格式校验通过后，用户可以测试并启用。

后续可增加“让 Agent 帮我写”功能。Agent 只生成草稿，不能自动启用、不能自行添加凭据、不能创造未注册 Tool，也不能把任意代码伪装成普通 Skill。

## 6.11 MCP 与 Plugin 后续页面

MCP 页面负责新建、导入、连接测试、启停和显示服务器状态；插件页面负责浏览和启停包含多个组件的完整扩展。首期 Skill 管理完成前，不开发复杂的 Plugin Marketplace。

---

## 7. Plugin Manifest 需求

建议结构：

```json
{
  "schema_version": 1,
  "id": "music.spotify",
  "name": "Spotify 音乐",
  "version": "1.0.0",
  "description": "搜索并控制 Spotify 播放",
  "publisher": "trusted-publisher",
  "source_type": "registry",
  "package_url": "https://registry.example/packages/music.spotify-1.0.0.zip",
  "package_hash": "sha256:...",
  "entry_type": "mcp",
  "skills": ["music-control"],
  "tools": [
    "spotify.search_track",
    "spotify.play_track",
    "spotify.pause"
  ],
  "permissions": [
    "network:spotify.com",
    "account:spotify-playback"
  ],
  "risk_summary": "可以控制你的 Spotify 播放设备",
  "settings_schema": {},
  "minimum_app_version": "0.2.0"
}
```

校验要求：

- `id + version` 唯一；
- 不允许未知顶层字段静默生效；
- Tool 名称必须使用插件命名空间；
- 权限声明必须覆盖实际行为；
- 安装时展示新增权限；
- 更新导致权限扩大时必须重新确认；
- App 版本不兼容时禁止启用；
- Manifest 不能包含明文凭据。
- `source_type` 必须是 registry、git、npm、url、local 或 custom；
- 网络来源必须记录原始地址、解析后的版本和内容哈希；
- 包内路径不得逃逸插件目录；
- 安装脚本默认禁止执行，仅开发者模式可单独授权。

---

## 8. 插件生命周期

### 8.1 状态

```text
available       可安装
installed       已安装、未配置
configured      已配置、未启用
enabling        正在连接或检查
enabled         已启用
unavailable     配置或依赖异常
disabling       正在停止
disabled        已禁用
update_required 需要更新
uninstalling    正在卸载
```

### 8.2 安装

1. 用户查看能力详情；
2. 系统验证来源、Manifest、版本和依赖；
3. 展示权限与风险；
4. 用户确认；
5. 保存插件记录；
6. 进入 installed；
7. 需要账号或 Provider 时引导配置；
8. 默认不自动启用高风险插件。

### 8.3 启用

- 验证配置完整；
- 验证凭据或 MCP 连接；
- 加载 Skill；
- 注册 Tool；
- 建立只读 Capability Snapshot；
- 将插件关联到 Assistant Profile；
- 健康检查通过后变为 enabled。

### 8.4 禁用

- 禁用只影响新 Run；
- 新 Run 不再收到对应 Skill 和 Tool Schema；
- 服务端再次校验插件状态，拒绝过期 Tool Call；
- MCP 连接可关闭；
- 已开始的外部动作不自动强制回滚；
- 正在运行的高风险动作存在时，禁用请求返回冲突或等待收尾；
- ToolRun 和历史消息继续保留。

### 8.5 卸载

- 必须先禁用；
- 删除插件配置、Skill 和本地包；
- OAuth Token/Secret 安全删除；
- 保留必要的历史审计摘要；
- 不删除由插件创建的用户外部数据，除非用户明确选择；
- 卸载后历史结果显示“该能力已卸载”。

---

## 9. Capability Snapshot

每个 AgentRun 开始时生成不可变快照：

```text
assistant_id
enabled_plugin_ids + versions
allowed_skill_ids
allowed_tool_names
tool risk levels
context provider flags
permission policy
created_at
```

要求：

- Run 执行中插件状态变化不修改该快照；
- 服务端执行 Tool 时仍检查插件没有被紧急停用；
- 快照只保存 ID 和版本，不保存凭据；
- ToolRun 记录来源插件；
- 失败可以还原当时可用能力集合；
- direct 和 planned 使用同一快照。

---

## 10. 权限与安全

## 10.1 权限类型

```text
读取个人资料
读取长期记忆
访问指定网络域名
读取本地目录
写入本地目录
运行命令
控制外部设备或软件
创建外部内容
发送消息/邮件
产生付费请求
创建后台任务
```

## 10.2 风险等级

| 等级 | 示例 | 默认策略 |
|---|---|---|
| low | 搜索歌曲、读取天气 | 允许已启用插件执行 |
| medium | 读取文件、读取日历 | 安装时授权，必要时逐次确认 |
| high | 写文件、发邮件、运行命令、购买 | 每次预览和审批；后台拒绝 |

风险等级由平台决定，Plugin 不能自行降低。

## 10.3 凭据管理

- API Key、OAuth Token 不存入 Prompt、Message、Plan、ToolRun 或 SSE；
- 数据库存引用或加密值，不返回完整凭据；
- 前端只显示已配置/未配置和末尾少量字符；
- 插件日志必须脱敏；
- 卸载或退出账号时撤销/删除凭据；
- v1 优先支持受信任插件，不开放任意第三方代码安装。

## 10.4 编码插件额外要求

- 必须选择 Workspace 根目录；
- 禁止访问根目录之外的路径；
- 命令执行有超时、输出限制和取消；
- 破坏性命令必须确认；
- 默认无网络；
- 建议运行在容器或受限子进程；
- 不继承主服务的全部环境变量；
- 插件关闭后新 Run 不再具有文件和命令工具。

---

## 11. 远期参考插件（非首期必做）

本章仅保留为未来扩展示例，不进入首批 Skill Manager 开发和验收。是否开发图片、音乐或编码插件，由后续真实需求和可用依赖决定。

## 11.1 图片生成插件

### 能力

```text
generate_image
edit_image（后续）
```

### 配置

- Provider；
- 模型；
- 默认尺寸；
- 输出目录；
- API Key/账号；
- 单次成本提示。

### 行为

- Skill 负责收集主题、风格、比例和用途；
- Tool 负责实际调用图片服务；
- 成功后使用统一媒体结果卡片；
- 失败不返回虚假图片；
- 关闭插件后不能调用生成服务。

## 11.2 音乐控制插件

### 能力

```text
search_track
play_track
pause_playback
resume_playback
next_track
get_current_track
```

### 配置

- 音乐服务；
- OAuth；
- 默认播放设备；
- 是否允许显式内容；
- 默认音量策略。

### 行为

- 多个同名歌曲时先澄清或使用最高相关项；
- 没有可用设备时明确提示；
- 播放成功后展示歌曲、歌手和设备；
- 插件关闭后不能保留控制入口；
- 不把完整 OAuth Token 发送给模型。

## 11.3 编码插件

### 能力

```text
read_file
search_files
edit_file
write_file
run_command
git_status
git_diff
```

### 行为

- 只对授权 Workspace 生效；
- 读写、命令和网络权限分别声明；
- 支持取消和输出截断；
- 修改前读取文件；
- 修改后运行相关测试；
- 高风险动作审批；
- 适合在插件系统稳定后开发。

---

## 12. 意图与能力选择

### 12.1 基本原则

不建立庞大的固定意图分类表。模型根据当前 Run 的 Tool Schema 和 Skill 选择能力，平台负责门控和权限。

### 12.2 决策顺序

```text
用户消息
→ 是否基础对话即可回答
→ 是否需要 Memory/RAG
→ 当前已启用能力中是否存在适合 Tool
→ 是否需要澄清参数
→ 是否需要审批
→ direct 执行或有限 planned 编排
```

### 12.3 缺少能力

当用户请求需要未启用能力时：

- 不调用未知工具；
- 不声称已经完成；
- 返回缺少的业务能力名称；
- 提供前往能力中心的入口；
- 不自动安装插件；
- 不把安装行为交给模型决定。

### 12.4 多插件冲突

例如同时安装 Spotify 和 Apple Music：

- 用户可设置默认插件；
- 未设置默认且请求不明确时询问；
- Skill/Tool 名称使用命名空间避免覆盖；
- 一个 Plugin 不可静默替换另一个 Plugin 的 Tool。

---

## 13. Planner 与 Activity 定位

## 13.1 Planner

Planner 不再作为基础聊天必选模式，而是复杂任务编排能力：

- 普通问答和单工具调用使用 direct；
- 多步骤任务可自动建议或由用户开启；
- Plan UI 默认折叠；
- Planner JSON 无效时安全停止；
- 提供重新规划或切换直接回答；
- Planner 不能安装、启用或修改 Plugin；
- Planner 只能使用 Run Snapshot 中已有工具。

## 13.2 Activity

Activity 面向用户显示为“提醒与任务”：

- 由用户创建或明确确认；
- Agent 不能自行建立长期任务；
- Activity 绑定 Assistant 和 Capability Snapshot 策略；
- 运行时重新获取当前已启用能力；
- 所需插件已禁用时失败并说明；
- 后台 high 工具继续直接拒绝。

---

## 14. 建议数据模型

### AssistantProfile

```text
id
user_id
name
avatar
identity
personality
response_style
response_length
initiative_level
user_address
custom_rules
default_model
memory_enabled
rag_enabled
created_at
updated_at
```

### Plugin

```text
id
plugin_key
name
version
publisher
manifest_json
status
source
installed_at
updated_at
last_error
```

### PluginConfig

```text
id
plugin_id
assistant_id
config_json（不含明文 Secret）
secret_reference
enabled
health_status
last_checked_at
```

### AssistantPlugin

```text
assistant_id
plugin_id
enabled
is_default_for_category
created_at
updated_at
```

### RunCapabilitySnapshot

```text
id
run_id unique
assistant_id
plugin_versions_json
skills_json
tools_json
policy_json
created_at
```

### 现有模型扩展

```text
Conversation.assistant_id
AgentRun.assistant_id
ToolRun.plugin_id
Activity.assistant_id
```

v1 可先创建默认 AssistantProfile，并把历史 Conversation 迁移到默认助手。

---

## 15. API 需求

### Assistant

```text
GET    /api/assistants
POST   /api/assistants
GET    /api/assistants/{id}
PATCH  /api/assistants/{id}
DELETE /api/assistants/{id}
POST   /api/assistants/{id}/preview
```

v1 若只支持单助手，可以只开放 GET/PATCH default assistant，保留内部多助手模型。

### Plugin

```text
GET    /api/plugins
GET    /api/plugins/{id}
POST   /api/plugins/{id}/install
PATCH  /api/plugins/{id}/config
POST   /api/plugins/{id}/test
POST   /api/plugins/{id}/enable
POST   /api/plugins/{id}/disable
DELETE /api/plugins/{id}
```

### 在线目录与自定义创建

```text
GET    /api/capability-catalog/search?q=&type=&trust=
GET    /api/capability-catalog/{key}
POST   /api/plugins/import
POST   /api/skills/drafts
PATCH  /api/skills/drafts/{id}
POST   /api/skills/drafts/{id}/generate
POST   /api/skills/drafts/{id}/validate
POST   /api/skills/drafts/{id}/test
POST   /api/skills/drafts/{id}/publish-local
GET    /api/skills/{id}/export
```

### Capability

```text
GET /api/assistants/{id}/capabilities
GET /api/runs/{id}/capabilities
```

### Chat 扩展

```json
{
  "conversation_id": "...",
  "assistant_id": "...",
  "message": "...",
  "knowledge_mode": "auto",
  "execution_mode": "direct"
}
```

已有调用缺少新字段时使用默认 Assistant、`knowledge_mode=auto` 和 `execution_mode=direct`。

---

## 16. 统一事件需求

保留现有事件，并新增通用能力事件：

```text
capability.selected
capability.unavailable
plugin.status.changed
plugin.authorization.required
plugin.authorization.completed
```

事件要求：

- 不包含 Secret；
- 不包含 MCP command；
- 不包含完整 Tool Result；
- 普通用户事件使用业务名称；
- 开发者诊断可额外包含 plugin_id、tool_name 和错误码；
- 前端未知事件必须安全忽略。

---

## 17. 非功能需求

### 17.1 稳定性

- Plugin 故障不能导致基础聊天不可用；
- 单个 Tool 失败后 Executor 可以继续生成解释；
- 禁用和卸载操作幂等；
- MCP 断连可标记 unavailable；
- 服务重启恢复 Plugin 状态，但不恢复半个外部写操作；
- 同一 Conversation 仍只允许一个 running Run。

### 17.2 性能

- 未启用插件不增加 Tool Schema token；
- Skill 按需或摘要加载；
- Capability Snapshot 构建目标小于 100ms；
- 禁用 Plugin 后不再保持不必要连接；
- 能力中心列表不触发全部远程连接；
- Plugin 健康检查与 Chat 请求解耦。

### 17.3 可用性

- 普通用户无需理解 MCP、Skill、Tool；
- 安装权限使用自然语言；
- 每个失败提供下一步操作；
- 高风险操作展示目标、影响和可撤销性；
- 移动端可以完成启用、禁用和授权；
- 无插件状态提供示例而非空白页面。

### 17.4 可扩展性

- Core 不依赖具体 Spotify、图片或编码实现；
- Plugin Tool 使用命名空间；
- Manifest 有 schema_version；
- Event 和 API 向后兼容；
- 通用设置 UI 使用 JSON Schema；
- v1 不承诺任意第三方代码兼容。

---

## 18. 基础聊天质量保障

不能承诺绝对无 Bug，但必须建立可重复验证的基础聊天契约。

### 18.1 固定回归集

至少覆盖：

```text
20 条普通中文对话
10 条角色一致性问题
10 条多轮指代问题
10 条 Memory 写入/召回/纠正/删除
10 条长会话摘要与预算问题
10 条 RAG 使用/跳过/无结果/引用问题
10 条模型失败、停止生成和并发问题
10 条插件启用/禁用隔离问题
```

### 18.2 必须成立

```text
□ 无插件时 Chat 完整可用
□ 安装插件但未启用，不改变 Chat Tool Schema
□ 启用插件，只增加声明的能力
□ 禁用插件，新 Run 无法调用对应 Tool
□ Plugin 故障不会污染 Memory 或角色设定
□ 长会话始终处于上下文预算内
□ Memory 冲突和用户纠正可处理
□ RAG 无实际引用时不显示来源
□ 不同 Conversation 和 Assistant 数据不串联
□ 后处理失败不把已完成回答标成失败
```

---

## 19. 开发阶段

### 阶段 A：基础助手稳定化

目标：建立后续插件系统不能破坏的稳定基线。

内容：

- Assistant Profile 数据模型与设置界面；
- 默认 Assistant 迁移；
- 基础聊天契约测试；
- Memory 冲突/纠正测试；
- RAG 自动/强制/禁用；
- 统一用户错误码；
- Planner 真实模型格式兼容和直接回答恢复。

验收：关闭所有可选能力时，基础聊天、角色、Memory、RAG 全量稳定。

### 阶段 B：本地 Skill 管理（首个扩展阶段）

目标：实现参考截图中的“技能”设置页，让目录里的 Skill 自动成为可选择的能力。

内容：

- Skill 索引扫描，包含启用、禁用、缺少依赖和格式错误项；
- AssistantSkill 数据模型，保存每个 Assistant 的开关状态；
- Skill 列表、搜索、详情、刷新和开关 API；
- “内置 / 本地导入”分组界面；
- 新 Run 使用不可变 Skill 快照；
- 内置 `time-helper`、`calculator-helper`、`writing-helper`、`summarize-helper`、`translate-helper`、`file-notes`；
- 关闭全部 Skill 后，基础聊天保持可用。

验收：把一个合法 Skill 文件夹放入 `personal-ai/skills/` 后，点击刷新即可在页面看到并启用；全过程不需要修改 Python 业务代码，也不需要重启服务。

### 阶段 C：Skill 导入与创建

目标：普通用户不手动操作项目目录，也能加入新的简单 Skill。

内容：

- 本地文件夹/ZIP 导入；
- 导入校验、冲突处理和安全解压；
- 可视化新建、编辑、测试、导出和删除；
- Agent 辅助生成 Skill 草稿；
- 缺少 Tool 的 Skill 给出明确提示，不尝试自动补装代码。

验收：导入或创建后自动出现在技能列表；无效 Skill 不影响其他 Skill 和基础聊天。

### 阶段 D：MCP 服务器管理

目标：实现独立的 MCP 页面，支持新建、导入、连接测试、启停、错误隔离和状态显示。

验收：MCP 关闭或故障时，相应 Tool 不可调用，但聊天和普通 Skill 仍可工作。

### 阶段 E：Plugin 与在线发现

目标：在本地 Skill 流程稳定后，再实现插件页以及 Git/URL/在线目录搜索安装。

内容：Plugin Manifest、依赖和权限提示、在线 Catalog、搜索、发布者、内容哈希、版本、兼容性、更新、回滚和外部来源隔离。

图片生成、音乐控制、浏览器自动化和编码能力属于此后按真实需求选择的参考扩展，不再作为首期必做项。

---

## 20. 暂不包含

- 普通模式静默执行任意网络来源中的第三方代码；
- 未经风险提示和用户确认启用无签名可执行插件；
- Plugin 任意注入前端 JavaScript；
- Agent 自主安装、启用、卸载 Plugin；
- Agent 自主创建长期 Activity；
- Multi-Agent；
- 通用 DAG；
- 分布式 Worker；
- 多租户 SaaS；
- 插件之间互相调用私有 Tool；
- 自动购买或不可逆外部操作。

---

## 21. 产品级验收标准

```text
□ 用户可以通过界面设计助手角色
□ 不安装插件时可以稳定长期聊天
□ Memory 与个人资料库职责清晰且可管理
□ 用户可以在独立页面查看 Skill、MCP 和 Plugin
□ 把合法 Skill 文件夹加入 skills 目录并刷新后，页面立即出现新选项
□ 每个 Assistant 可以分别启用和禁用 Skill
□ 用户可以导入本地文件夹/ZIP，也可以自己创建简单 Skill
□ 在线目录搜索和 Plugin 安装作为本地 Skill 稳定后的阶段验收
□ 用户可以从本地创建、验证、测试和启用 Skill
□ Agent 可以生成 Skill 草稿，但不能自动启用或扩大权限
□ Git/npm/URL 外部来源仅在开发者模式并经过校验安装
□ 启用 Plugin 后模型只能获得声明能力
□ 禁用 Plugin 后新 Run 无法调用其 Tool
□ Skill 不能创造不存在的执行能力
□ MCP 故障不会导致基础聊天失败
□ Plugin 权限和风险对普通用户可理解
□ Secret 不进入 Prompt、Message、Plan、ToolRun、SSE 和日志
□ 首批简单内置 Skill 完成端到端测试
□ 编码插件只访问用户授权 Workspace
□ 所有 Plugin 行为有 Run 和 ToolRun 记录
□ 安装、启停和卸载不会破坏已有对话、记忆和资料
□ 基础聊天固定回归集全部通过
□ 插件隔离和越权安全测试全部通过
□ 后端全量测试、RAG/Planner 评测和前端构建全部通过
```

---

## 22. 开发决策基线

后续代码开发必须遵守以下决定：

1. 基础助手和扩展能力分层；
2. 普通用户分别管理 Skill、MCP 和 Plugin；Tool 仍由系统内部管理；
3. Skill 只提供说明，Tool/MCP 才提供执行能力；
4. Plugin 禁用必须同时从模型和服务端执行链路移除；
5. 每个 Run 使用不可变 Capability Snapshot；
6. Memory 保存用户事实，RAG 保存和检索大段资料；
7. Planner、Activity 不能安装或扩大能力；
8. v1 先支持内置 Skill、目录扫描、开关和本地导入；在线社区与任意外部来源按阶段 E 开放；
9. 先完成阶段 A，再开发轻量 Skill Manager，不提前开发完整 Plugin Runtime；
10. 每完成一个阶段，更新本需求文档和对应开发报告。

---

## 23. 下一步

需求确认后，先完成阶段 A 的基础稳定项，再进入轻量 Skill Manager。首批 Skill Manager 开发任务：

```text
1. Skill 扫描结果包含启用、禁用、缺少依赖和错误状态
2. AssistantSkill 开关状态模型与 API
3. 技能列表、搜索、详情、刷新和开关页面
4. 增加 calculator/writing/summarize/translate 四个简单 Skill
5. 验证启用、禁用和不同 Assistant 之间的隔离
6. 验证关闭所有 Skill 后基础聊天完全可用
```

本地 Skill 的列表、开关、刷新和隔离验收通过后，再开发 ZIP 导入和可视化新建；MCP 页面、Plugin Runtime 和在线市场依次后置。
