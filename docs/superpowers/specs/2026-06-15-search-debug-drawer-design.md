# 设计文档：Search Debug Drawer

- **日期**：2026-06-15
- **产品**：Glomi AI
- **关联 Epic**：E3 超级对话调优、E4 深度研究中文化
- **状态**：一期已实施，并通过聚焦后端单测、前端 Jest 与类型检查

---

## 背景

平台默认 Glomi Search Gateway 已经接入 `web_search(mode=lite|deep)`。下一步需要一个轻量调试入口，用来解释 Agent 实际搜了什么、用了什么 provider/mode/channel、Gateway 返回了哪些 URL、耗时多少、失败在哪里。

这个能力面向开发和管理员排障，不面向普通用户做产品展示。

## 目标

1. 在聊天 timeline 的 Web Search 工具块内增加 Search Debug Drawer。
2. 后端随 `web_search` 工具执行流式发送 debug packet。
3. Debug 信息不落库、不持久化到独立表。
4. 不暴露 API key、Gateway base URL、Authorization header。
5. 保留现有 `search_tool_start`、`search_tool_queries_delta`、`search_tool_documents_delta` 事件，不破坏旧 UI。

## 非目标

- 不做全局 Search Debug Dashboard。
- 不做搜索日志持久化。
- 不把 `web_search` 和后续 `open_url` 强行绑定成一个调试对象。
- 不展示 Gateway 的敏感配置。

## Debug Packet

新增 streaming packet：

```json
{
  "type": "search_tool_debug_delta",
  "provider_type": "glomi",
  "provider_name": "Glomi Search",
  "mode": "deep",
  "channel": "tavily",
  "queries": ["..."],
  "duration_ms": 432,
  "result_count": 8,
  "results": [
    {
      "title": "...",
      "url": "https://...",
      "snippet": "..."
    }
  ],
  "failed_queries": {},
  "error": null
}
```

字段说明：

- `provider_type` / `provider_name`：当前 active search provider。
- `mode`：本次工具调用最终使用的 `lite` 或 `deep`，包括默认值补齐后的结果。
- `channel`：provider config 中的非敏感 channel，可为空。
- `queries`：Agent 实际传入的 query portfolio。
- `duration_ms`：provider 调用和过滤结果的耗时。
- `results`：过滤后的搜索结果摘要，只含 title/url/snippet。
- `failed_queries`：per-query provider 的部分失败信息；batch provider 失败则走 `error`。
- `error`：整体失败原因。失败时也尽量发 debug packet，再抛 `ToolCallException`。

## 前端展示

在 `WebSearchToolRenderer` 的 FULL 模式中，查询 chips 下方显示一个折叠面板：

- 标题：`Search debug`
- 摘要行：`provider · mode · channel · duration · result count`
- 展开后展示 queries、results URL 列表、失败 query 和整体错误。

COMPACT / INLINE / HIGHLIGHT 模式不额外展示 debug，避免 timeline collapsed 状态太吵。

## 权限与隐私

第一期不新增后端权限分支，因为 packet 本身不包含密钥、base URL 或 header。前端展示放在工具块内折叠，默认收起。后续如果要给普通用户隐藏，可以加 user role gate 或开发开关。

## 测试

- 后端 unit test：`WebSearchTool` 成功时 emit `search_tool_debug_delta`，包含 provider/mode/channel/queries/duration/results。
- 后端 unit test：per-query 部分失败时 debug packet 包含 `failed_queries`。
- 后端 unit test：batch provider 失败时 debug packet 包含 `error`，随后仍抛 `ToolCallException`。
- 前端 unit test：`constructCurrentSearchState()` 能从 debug packet 提取 debug 信息。
- 前端 unit test：`isSearchToolPacket()` 识别 debug packet，保证它留在 search tool group。
- 验证：focused backend pytest、focused frontend jest、`web npm run types:check`。
