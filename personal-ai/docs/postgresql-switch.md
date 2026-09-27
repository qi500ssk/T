# PostgreSQL 切换记录

2026-09-24 按用户要求恢复本机 PostgreSQL + pgvector。

- 当前库：`personal_ai_current_20260924`，本机端口 5432。
- 原 SQLite：`data/personal-ai.db`，保留不删除。
- 一致性备份、逐表校验报告、旧连接配置及原运行时设置：`data/backups/postgres-switch-20260924-135207/`。
- 账号、登录会话、28 条消息、23 次运行、7 条角色记忆、2 条长期记忆和其他业务记录已迁移。迁移时世界书文档表为 0 条，并非切换导致文档丢失。
- PostgreSQL schema：`20260924_13`。关键词模式的空向量映射为 NULL，真实向量以 pgvector 存储。

启动：项目目录执行 `docker compose up -d postgres`，然后按原命令启动后端和前端。`.env` 已指向新库，不要恢复为旧库地址。

回退前必须先停止后端，并备份切换后产生的 PostgreSQL 新数据。`previous.env` 是切换前的 SQLite 连接配置；恢复它只会读取切换前数据，不能自动合并 PostgreSQL 的新聊天。不要在两套数据库上同时运行写入。

回归：PostgreSQL 隔离临时库 358 项通过、2 项跳过；SQLite 366 项通过、1 项跳过。前端构建、lint 与模拟浏览器交互通过。运行中的 PostgreSQL 记忆查询已验证，不再触发缺表 500。
