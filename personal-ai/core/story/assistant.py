"""Stable identity and product behavior of the built-in writing assistant."""
ASSISTANT_ID = "story-author"
OPENING = "我是你的小说与世界创作助手。这是一次独立的新对话，我们从你的想法开始。你想创作一个新故事，阅读已有小说并创建角色，还是继续一本已有作品？"
OPENING_OPTIONS = ["创作新的小说与世界", "导入已有小说，阅读并创建角色", "继续已有作品，由我选择资料"]


def is_story_assistant(agent_id):
    return agent_id == ASSISTANT_ID
