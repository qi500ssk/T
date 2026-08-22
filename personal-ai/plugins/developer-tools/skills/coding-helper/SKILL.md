---
name: coding-helper
description: 当用户明确要求查看、搜索、创建、修改或检查编码工作区中的项目代码时使用；不用于普通聊天或文档生成。
allowed-tools: code_list_files code_search code_read code_create_file code_edit code_git_diff code_run_check
metadata:
  personal-ai:
    enabled: true
    source: local
---
仅处理 `CODING_WORKSPACE_DIR` 指向的编码工作区。不要把普通聊天、知识库资料或生成文档误当成代码工作区。

开始修改前，先用 `code_list_files`、`code_search` 和 `code_read` 确认现有结构、调用关系与用户已有改动。优先做范围小、可验证的修改：

- 新文件使用 `code_create_file`，它不会覆盖已有文件；
- 已有文件使用 `code_edit`，提供只出现一次的精确 `old_text` 和替换后的 `new_text`；
- 修改后重新读取相关片段；如果工作区是 Git 仓库，再用 `code_git_diff` 检查实际改动；
- 根据项目类型使用 `code_run_check`。可选检查为 `pytest`、`python-compile`、`npm-test`、`npm-lint`、`npm-build` 和 `npm-typecheck`。

创建、修改和运行项目代码都需要用户审批。一次审批只授权当前工具调用，不代表允许后续写入或执行。

本能力没有删除、移动、任意 Shell、安装依赖、联网、Git 提交、推送或回滚工具。不得声称执行了未提供的能力，也不得使用其他文件工具绕过编码工作区和审批限制。检查未通过时保留真实错误并说明下一步，不要宣称任务已经完成。
