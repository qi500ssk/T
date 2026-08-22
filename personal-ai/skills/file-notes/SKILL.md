---
name: file-notes
description: 读取和保存沙箱中的文本笔记
required_tools: [read_file, write_file]
enabled: true
source: builtin
---
需要了解已有内容时先调用 read_file；需要保存内容时调用 write_file。
write_file 会由系统请求用户确认，未经批准不得声称写入成功。
