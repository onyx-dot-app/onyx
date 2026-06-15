# 设计文档：平台默认 Glomi Search Gateway 与 Agent 搜索模式

- **日期**：2026-06-15
- **产品**：Glomi AI
- **关联 Epic**：E3 超级对话调优、E4 深度研究中文化
- **状态**：已确认设计，等待实施计划
- **相关设计**：
  - `2026-06-14-platform-default-openai-compatible-llm-design.md`
  - `2026-06-13-agent-search-and-research-strategy-design.md`

---

## 1. 背景

Glomi AI 已经把 LLM Provider 纠偏为“平台默认 OpenAI-compatible 主模型自动初始化”：用户注册或 tenant 初始化后即可使用，不需要进入 Admin 配置模型。

搜索能力也需要同样的产品形态：用户不配置搜索引擎、不理解 Tavily/Brave/Serper/Exa，只提出问题，由 Agent 决定是否搜索、如何搜索，并由平台统一提供默认搜索能力。

但搜索和 LLM Provider 有一个关键差别：Glomi 已经在 E3/E4 中做了“中文 Agent 搜索与研究能力层”，核心不只是接一个搜索 API，而是让 Agent 掌握搜索方法论：

- 何时搜索。
- 生成什么 query portfolio。
- 搜什么来源。
- 何时 open_url。
- 如何处理 Lite / Deep 搜索强度。
- 如何把证据交给回答或深度研究流程。

因此本设计不是单纯“seed 一个 Tavily key”，而是把 Onyx 的 `web_search` 工具接入 Glomi 自己的 Search Gateway，并让 Agent 在工具调用中选择 `lite` 或 `deep` 搜索模式。

---

## 2. 目标

1. 新 tenant 或单租户初始化时，自动 seed 一套平台默认 Web Search Provider。
2. Onyx 侧只接 `Glomi Search Gateway`，不直接接 Tavily 官方 API。
3. 第一阶段 Gateway 内部默认渠道为 Tavily，但 Onyx 不绑定 Tavily 协议。
4. 配置保持极简：
   - `GLOMI_DEFAULT_WEB_SEARCH_API_BASE`
   - `GLOMI_DEFAULT_WEB_SEARCH_API_KEY`
   - `GLOMI_DEFAULT_WEB_SEARCH_CHANNEL` 可选，第一期可设为 `tavily`
5. 复用 Onyx 原生 `InternetSearchProvider`、`WebSearchTool`、Admin Web Search 管理链路。
6. `web_search` 工具支持 Agent 在同一次工具调用中选择 `mode=lite|deep`。
7. 不增加前置 `SearchModeRouter` LLM 调用，不因为搜索模式判断额外消耗一次模型调用。
8. 不做代码层关键词规则匹配，搜索模式由 Agent 通过工具调用参数决定。
9. Deep Research 的 research agent 默认使用 `deep` 搜索模式。
10. `open_url` 第一阶段继续使用 Onyx 默认 `OnyxWebCrawler`，不接入 Gateway 内容抓取。

---

## 3. 非目标

- 不在 Onyx 中直接实现 Tavily client 作为最终产品边界。
- 不把 Tavily/Brave/Serper/Exa 等来源暴露给 C 端用户。
- 不做关键词、正则、规则表来判断 Lite / Deep / Research。
- 不新增前置 LLM router 来判断搜索模式。
- 不在本期自动把普通聊天升级成完整 Deep Research 工作流。
- 不把完整 Deep Research 塞进 `web_search` 工具。
- 不 seed `InternetContentProvider`。
- 不重写 `llm_loop` 或 `dr_loop`。
- 不做完整搜索 Debug 面板；可在后续单独立项。

---

## 4. 核心架构

本设计把搜索能力分成两层：

```text
Onyx / Glomi Agent runtime
  -> 判断是否使用 web_search
  -> 生成 query portfolio
  -> 选择 mode=lite|deep
  -> 决定是否继续 open_url

Glomi Search Gateway
  -> 接收 queries + mode + channel
  -> 调 Tavily 或未来其他搜索来源
  -> 去重、重排、来源均衡、返回统一结果
```

Onyx 仍然是 Agent 的“搜索认知层”；Gateway 是“搜索执行与聚合层”。

这能保留现有 E3/E4 prompt/playbook 的价值，同时把搜索供应商切换、Tavily 参数、未来多来源融合留在 Gateway 内部演进。

---

## 5. 搜索模式模型

搜索模式不是 UI 按钮，也不是代码规则。它是 Agent 调用 `web_search` 时的工具参数。

第一阶段支持：

```text
no_search   Agent 不调用 web_search
lite        Agent 调 web_search(mode="lite")
deep        Agent 调 web_search(mode="deep")
```

完整 Deep Research 是另一种工作流，不属于 `web_search.mode`：

```text
deep_research -> run_deep_research_llm_loop()
```

本期只让 Deep Research 内部的 research agent 默认使用 `web_search(mode="deep")`。普通聊天自动升级到完整 Deep Research 以后应通过独立工具或 orchestrator 设计解决，不在本期把它混入 `web_search`。

### 5.1 Lite 搜索

`lite` 用于普通对话里的轻量信息获取：

- 低延迟优先。
- 返回较少但更高信号的结果。
- 适合简单事实更新、产品状态、价格、版本、近期信息补全。
- Gateway 可使用 Tavily 的快速策略。
- Onyx 回答形态仍保持简洁。

### 5.2 Deep 搜索

`deep` 用于普通对话或研究 agent 中的高召回搜索：

- 来源多样性优先。
- 更重视官方源、primary source、反方证据和跨 query 去重。
- 适合事实核查、复杂对比、风险判断、市场/技术选型。
- Gateway 可使用 Tavily 的深度策略或多来源融合。
- 普通聊天仍可以 deep search，但不自动变成长报告。

---

## 6. 配置设计

显式开关：

```env
GLOMI_DEFAULT_WEB_SEARCH_ENABLED=true
```

必填配置：

```env
GLOMI_DEFAULT_WEB_SEARCH_API_BASE=https://search-gateway.example.com
GLOMI_DEFAULT_WEB_SEARCH_API_KEY=...
```

可选配置：

```env
GLOMI_DEFAULT_WEB_SEARCH_CHANNEL=tavily
```

内部固定值：

- provider name：`Glomi Search`
- provider type：`glomi`

`channel` 的语义：

- 配置时，Onyx 请求 Gateway 时传给 Gateway。
- 不配置时，Onyx 不传，由 Gateway 使用自己的默认渠道。
- 后续 Tavily、Brave、Serper、自研混合搜索的策略优先在 Gateway 内演进。

---

## 7. Seed 行为

### 7.1 执行位置

沿用默认 LLM Provider 的初始化位置：

1. 单租户 / 本地启动：`backend/onyx/setup.py:setup_postgres()`
2. 新 tenant 初始化：`backend/ee/onyx/server/tenants/provisioning.py:configure_default_api_keys()`

### 7.2 幂等规则

按 provider name + provider type 查找：

- 不存在：创建 `Glomi Search / glomi` provider。
- 已存在：更新 api key、base URL、channel 等配置。
- 缺配置或 disabled：跳过，不阻塞服务启动。
- 如果当前没有 active web search provider：把 Glomi Search 设为 active。
- 如果当前 active provider 是 `glomi`：保持 Glomi Search active 并更新配置。
- 如果当前 active provider 是管理员手动启用的非 Glomi provider：不强行覆盖，避免启动时偷偷改回平台默认。

### 7.3 不处理内容读取 provider

本期不 seed `InternetContentProvider`。

`open_url` 继续走现有默认逻辑：没有 active content provider 时使用 `OnyxWebCrawler`。

---

## 8. WebSearchTool 契约

当前 `web_search` 工具只接受：

```json
{
  "queries": ["..."]
}
```

本设计扩展为：

```json
{
  "queries": ["..."],
  "mode": "lite"
}
```

或：

```json
{
  "queries": ["..."],
  "mode": "deep"
}
```

`mode` 在 schema 描述中强引导 Agent 必填，但运行时为兼容旧模型输出，应允许缺省：

- 普通 chat 缺省为 `lite`。
- Deep Research / research agent 缺省为 `deep`。

这不是代码规则匹配，只是工具参数缺省值，避免模型漏参导致工具失败。

`WebSearchTool` 仍负责：

- 接收并清洗 query 列表。
- 发出 `search_tool_queries_delta`。
- 调 provider。
- 过滤无 title/snippet 的结果。
- 转成 `SearchDocsResponse`。
- 发出 `search_tool_documents_delta`。

但 provider 调用需要携带 `mode`。

---

## 9. Gateway 协议

Onyx 调 Gateway：

```http
POST {GLOMI_DEFAULT_WEB_SEARCH_API_BASE}/search
Authorization: Bearer <GLOMI_DEFAULT_WEB_SEARCH_API_KEY>
Content-Type: application/json
```

请求体：

```json
{
  "queries": [
    "Tavily search API pricing 2026",
    "Tavily API docs search_depth"
  ],
  "mode": "deep",
  "channel": "tavily",
  "max_results": 20,
  "locale": "zh-CN"
}
```

说明：

- `queries` 是数组，不是单 query，方便 Gateway 做跨 query 去重和重排。
- `mode` 为 `lite` 或 `deep`。
- `channel` 可选。
- `locale` 第一阶段固定 `zh-CN`，后续可从用户语言或租户配置推导。
- `max_results` 由 Onyx 根据模式或 provider config 决定。

响应体：

```json
{
  "results": [
    {
      "title": "...",
      "url": "https://...",
      "snippet": "...",
      "published_date": "2026-06-15T00:00:00Z",
      "author": "...",
      "source_type": "official",
      "score": 0.82
    }
  ]
}
```

Onyx 第一阶段使用：

- `title`
- `url` 或 `link`
- `snippet`
- `published_date`
- `author`

`source_type` 和 `score` 可先忽略，但保留给后续 debug、重排和证据质量展示。

---

## 10. 错误处理

Glomi Search Client 需要把 Gateway 错误转换成清晰的 provider 错误：

- 401 / 403：`Invalid Glomi Search API key`
- 429：`Glomi Search rate limit exceeded`
- 5xx / 网络错误：可重试，失败后返回 provider failed
- 超时：默认超时，不无限等待
- 非 JSON 响应：报 provider failed，不把 HTML 或错误页传给 LLM
- 单个 query 失败但其他 query 成功：保留成功结果，记录 warning
- 全部 query 失败：沿用 `WebSearchTool` 的 `ToolCallException` 机制

Seed 阶段缺配置时只写 warning，不阻塞服务启动。

---

## 11. Prompt 与 Agent 行为

本期不增加前置 SearchModeRouter，也不做代码层规则匹配。

需要调整 prompt / tool guidance，让主 Agent 在同一次工具调用中决定：

- 是否调用 `web_search`。
- 调用时使用 `mode=lite` 还是 `mode=deep`。
- 搜索后是否 `open_url`。

普通 chat：

- `WEB_SEARCH_GUIDANCE` 说明 `mode` 的语义。
- Agent 自己判断本轮搜索强度。
- 不搜索时不调用工具。

Deep Research：

- research agent 的 `WEB_SEARCH_TOOL_DESCRIPTION` 说明默认使用 `mode=deep`。
- 如果模型漏传 mode，后端 override 默认 `deep`。

这保持了用户期望：搜索智能来自 Agent 对任务的理解，而不是 UI 开关或后端关键词规则。

---

## 12. 前端与 Admin

C 端用户不需要看到搜索 provider 配置。

Admin Web Search 页面需要能识别 `glomi` provider type，至少不崩溃：

- provider type 列表包含 `glomi`。
- 配置字段可显示 base URL / channel。
- API key 继续使用 masked key。

普通聊天流式 UI 不需要新增模式 UI。现有事件仍可用于调试：

- `search_tool_start`
- `search_tool_queries_delta`
- `search_tool_documents_delta`
- `open_url_start`
- `open_url_urls`
- `open_url_documents`

后续可以单独做 Search Debug 面板，展示 provider、mode、channel、queries、URL、耗时和失败原因。

---

## 13. 测试

后端 unit tests：

1. 默认搜索配置缺 disabled / api base / api key 时跳过并返回明确 reason。
2. seed 创建 `Glomi Search / glomi` provider。
3. seed 更新已存在的 Glomi provider。
4. 没有 active provider 时设 Glomi active。
5. active provider 已是 Glomi 时保持 active。
6. active provider 是非 Glomi 时不覆盖。
7. `GlomiSearchClient` 发出 batch queries、mode、channel、max_results、locale。
8. Gateway 响应支持 `url` 和 `link`。
9. Gateway 错误状态映射清楚。
10. `WebSearchTool` 接受 `mode=lite|deep`，并在缺省时使用 override default。
11. Deep Research / research agent 路径默认 `deep`。

Prompt tests：

1. 普通 `WEB_SEARCH_GUIDANCE` 包含 `mode=lite|deep` 指导。
2. Deep Research research agent prompt 包含 `mode=deep` 指导。
3. `.format(...)` 调用不因新增 JSON 示例中的 `{}` 破坏。

前端 tests：

- 如需更新 web search provider type，跑对应 TypeScript 类型检查。

验证命令：

```powershell
$env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m pytest <focused backend tests>
cd web; npm run types:check
```

---

## 14. 风险与取舍

### 风险 1：模型漏传 mode

用工具 schema 和 prompt 强引导，同时后端给缺省值。普通 chat 默认 `lite`，Deep Research 默认 `deep`。

### 风险 2：Deep 模式被滥用导致成本上升

本期不做代码规则限制。先通过 benchmark 观察真实使用，再决定是否在 Gateway 侧做成本阈值或速率限制。

### 风险 3：Gateway 协议过早绑定 Tavily

Onyx 只传 `channel=tavily`，不传 Tavily 专有参数。Tavily 的 `search_depth`、include domains、rerank 等由 Gateway 翻译。

### 风险 4：不做前置 Router 会不会不够智能

本期把决策合并到主 Agent 的工具调用里，避免每轮额外 LLM 调用。若后续发现主 Agent 稳定性不足，再考虑把完整 Deep Research 做成可调用工具，而不是加独立前置 router。

---

## 15. 验收标准

1. 本地或新 tenant 启动后能自动拥有 active `Glomi Search / glomi` provider。
2. 用户无需配置搜索 provider 即可触发 `web_search`。
3. 普通 chat 的 Agent 能在工具调用中选择 `mode=lite` 或 `mode=deep`。
4. Deep Research 的 research agent 默认使用 `deep` 搜索。
5. Gateway 能收到 `queries + mode + optional channel`。
6. 搜索结果仍通过 Onyx 原有 citation / open_url / timeline 链路展示。
7. 已有非 Glomi active provider 不被启动 seed 强制覆盖。
8. 不新增额外 SearchModeRouter LLM 调用。
9. 不引入后端关键词规则匹配。

---

## 16. 后续边界

后续可以独立立项：

- Search Debug 面板。
- Gateway 多来源聚合策略。
- source_type / score 展示与证据质量评估。
- `deep_research` 作为主 Agent 可调用工具。
- 成本、限流、渠道 fallback。
- 内容读取 provider 接入 Gateway 或 Firecrawl。
