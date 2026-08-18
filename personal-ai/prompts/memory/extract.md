TASK: MEMORY_EXTRACTION

从本轮对话中提取值得跨会话长期保存的用户信息。只记录用户明确表达的事实，不能把助手的推测当作事实。

返回严格 JSON，不要使用 Markdown：
{"memories":[{"key":"稳定的英文点分键","kind":"profile|semantic|episodic","content":"独立、简洁的中文事实","importance":1,"confidence":0.0}]}

规则：
- profile：身份、稳定偏好、习惯；semantic：长期事实；episodic：值得记住的事件。
- 临时请求、寒暄、敏感凭据、助手生成的内容不应保存。
- 同一类偏好使用相同 key，使新事实可以替换旧事实。
- importance 为 1-5，confidence 为 0-1；没有合适内容时返回 {"memories":[]}。
