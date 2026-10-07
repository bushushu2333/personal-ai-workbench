# 任务看板接入约定

在本地 config.local.json 设置 task_board_root。该目录包含生成的 index.html 及 tasks-data/*.md。工作台不会运行生成器或修改这个来源目录。

index.html 的最小数据约定：

```html
<script id="task-data" type="application/json">
[{"id":"example-task","title":"示例任务","status":"progress","priority":1,"summary":"虚构示例","next":["确认目标"],"log":[],"strategy":[],"subtasks":[]}]
</script>
```

id 是 1–100 位字母、数字、连字符或下划线。标题必填，priority 为 0/1/2，next/log/strategy 是字符串数组。其他可选展示字段为 subtitle、brief、blocker、milestone、note、decision、date。子任务用 subtasks，层级最多 8 层；所有 id 唯一。

列表卡片使用 `.task-row[data-task="example-task"]`，列表容器为 `#task-list`。嵌入适配器会给已知任务加“复制 HTML 路径”按钮，并在过滤重新渲染后补回按钮。按钮不嵌套在原卡片按钮中。

对应 tasks-data/example-task.md 使用 YAML frontmatter：id、title、status、priority、brief、updated。正文支持概要、当前卡点、下一步、事件日志章节。生成器负责将其转换为页面任务数组。工作台只将已声明的展示字段交接给 AI，不整体复制原始 Markdown 或任意元数据。

白名单资源为 index.html、style.css、common.js、assets/avatar.svg、assets/hero.svg 及 tasks 下一级 HTML 文件。不要直接挂载任务目录。外部看板如需要更多资源，须单独审阅后增加明确的允许路径；归档、配置和生成器不能通过静态接口访问。

嵌入页面有独立 sandbox 与 CSP。只允许相应页面脚本的哈希和本地静态资源，不允许页面向外联网。生成器必须安全转义 JSON/HTML；参考内置虚构示例，勿在任务数据中放置凭据。

任务独立页与导出快照在 data/task-pages 内生成。复制是本地路径交接；跨电脑需要发送下载文件，分享前检查内容。
