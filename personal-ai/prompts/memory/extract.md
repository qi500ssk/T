TASK: MEMORY_EXTRACTION

从本轮对话中提取值得跨会话长期保存的用户信息。只记录用户明确表达的事实，不能把助手的推测当作事实。

返回严格 JSON，不要使用 Markdown：
{"memories":[{"key":"稳定的英文点分键","kind":"profile|semantic|episodic","scope":"agent|project|conversation","content":"独立、简洁的中文事实","importance":1,"confidence":0.0}]}

规则：
- profile：身份、稳定偏好、习惯；semantic：长期事实；episodic：值得记住的事件。
- scope 判断要保守：用户明确说“以后都/总是/记住”的稳定偏好、身份信息以及与当前 AI 好友的关系 → agent；明确针对当前项目的技术约定和项目事实 → project；其余任何情况（包括无法确定）一律 conversation。自动提取不得创建公共 global 记忆。
- “这次/这一次”等一次性请求、寒暄、敏感凭据、助手生成的内容不应保存。
- 同一类偏好使用相同 key，使新事实可以替换旧事实。
- importance 为 1-5，confidence 为 0-1；没有合适内容时返回 {"memories":[]}。
