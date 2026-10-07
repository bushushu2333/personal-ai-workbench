# 可选 AI 来源

默认暂停所有 AI 状态采集。页面启用所需实例后，才读取相关来源。关闭全部实例后不再扫描 AI 进程或读取其状态来源。

## 本机 bridge

Codex / ZCode / Kimi 使用兼容的只读 bridge；此项目不附带 bridge。config.local.json 的 bridge_url 仅接受本机 HTTP 地址，默认端口 8791。只读取 GET /healthz 和 GET /status，不发送确认、执行或结束任务指令。

GET /healthz 返回 200，GET /status 返回：

```json
{
  "ts": 1780000000,
  "codex": {
    "ok": true,
    "running": 1,
    "waiting": 0,
    "items": [{"id": "demo-event", "t": "44656d6f", "s": "R", "a": 10}]
  }
}
```

ts 为 Unix 秒或可解析的 ISO 时间；t 为 GB2312 编码标题的十六进制，s 为 R（执行）或 W（完成待查看），a 为相对 ts 的活动秒数。zcode、kimi 使用相同结构。每个来源只展示前 5 个活动，并明确标记截断；不把已观察到的标题数量当成完整任务数。

bridge 计数只是来源报告。Codex 的活动推断、应用进程在线与实际业务任务进行中不是同一件事。45 秒以上的来源快照标记过期；失败不会伪造零任务。

## Hermes

仅在 Hermes 实例启用后读取本机 `.hermes/gateway_state.json`。使用 pid、updated_at、gateway_state、active_agents 白名单字段；不读会话正文或认证文件。历史快照不会被当成可靠的当前空闲计数。

任何已读取的标题或状态只存本地，发现页的公共数据请求不会携带它们。
