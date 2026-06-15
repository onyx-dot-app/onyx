# 所有相关的变动都需要记录在summary.md中，包括坑，经验，变动等等；关于产品相关的文档在docs/GlomiAI.md，有产品相关变动了需要同步更新这个文件

## 2026-06-15

- 重新生成顶层 `README.md`：从上游 Onyx 项目介绍切换为 GlomiAI 中文主 README，围绕 C 端消费级超级 Agent 定位、Phase A 核心能力验证、平台默认 OpenAI-compatible LLM、Glomi Search Gateway、Search Debug Drawer、本地开发/验证命令和开发约束重组；保留 Onyx/MIT 来源与正式发布前需复核授权边界的提醒。
- 完善顶层 `README.md`：新增当前分支状态表，明确 E1/E2/E3/E4、Glomi Search Gateway、adapter 架构、Search Debug Drawer、Craft/E13/商业化模块的已做与待做；补充平台默认 LLM seed、中文搜索/研究方法论、`web_search` lite/medium/deep、Gateway adapter service、Search Debug streaming packet 的逻辑链路说明。
- 新增设计文档 `docs/superpowers/specs/2026-06-15-platform-default-glomi-search-gateway-design.md`：搜索配置方向确认参考 E2 默认 LLM Provider，平台自动 seed `Glomi Search / glomi` 到 Onyx 原生 `InternetSearchProvider` 架构。
- 关键决策：Onyx 侧只接 Glomi Search Gateway，不直接绑定 Tavily 官方协议；第一期 Gateway 内部默认渠道可走 Tavily，后续 Tavily/Brave/Serper/自研聚合在 Gateway 内演进。
- 配置收敛：`GLOMI_DEFAULT_WEB_SEARCH_ENABLED`、`GLOMI_DEFAULT_WEB_SEARCH_API_BASE`、`GLOMI_DEFAULT_WEB_SEARCH_API_KEY`、可选 `GLOMI_DEFAULT_WEB_SEARCH_CHANNEL=tavily`；不 seed `InternetContentProvider`，`open_url` 继续走 Onyx 默认 `OnyxWebCrawler`。
- E3/E4 搜索模式修正：Lite / Medium / Deep 不由 UI 是否普通聊天或是否打开 Deep Research 决定，也不做后端关键词规则匹配；Agent 在同一次 `web_search` 工具调用中传 `mode=lite|medium|deep`，不额外增加前置 SearchModeRouter LLM 调用。
- Deep Research 边界：完整 Deep Research 仍是独立研究工作流，本期只让 research agent 默认使用 `web_search(mode=deep)`；未来若要普通主 Agent 自动进入完整研究，应单独设计 `deep_research` 工具或 orchestrator，不塞进 `web_search`。
- 同步更新 `docs/GlomiAI.md`：Phase A 纳入平台默认 Glomi Search Gateway 与 Agent 自动 Lite/Medium/Deep 搜索模式，默认搜索服务决策标记为已定。
- 新增实施计划 `docs/superpowers/plans/2026-06-15-platform-default-glomi-search-gateway.md`，按 backend seed/client/tool mode、Deep Research 默认 deep、Admin provider 类型、文档与验证拆分。
- 实现平台默认搜索 provider seed：新增 `backend/onyx/db/glomi_search.py`，从 `setup_postgres()` 和 tenant provisioning 调用；配置项为 `GLOMI_DEFAULT_WEB_SEARCH_ENABLED`、`GLOMI_DEFAULT_WEB_SEARCH_API_BASE`、`GLOMI_DEFAULT_WEB_SEARCH_API_KEY`、`GLOMI_DEFAULT_WEB_SEARCH_CHANNEL`，只在无 active provider 或 active provider 已是 Glomi 时激活，避免覆盖管理员手动启用的其他搜索服务。
- 实现 `GlomiSearchClient` 与 `WebSearchProviderType.GLOMI`：Onyx 通过 Gateway batch `/search` 协议发送 `queries + mode + optional channel + max_results + locale=zh-CN`，支持响应中的 `url` / `link`，并映射鉴权、限流、5xx、网络和非 JSON 错误。
- 扩展 `web_search` 工具契约：新增 `WebSearchMode(lite|medium|deep)`，普通 chat 缺省 `lite`，Deep Research research agent 缺省 `deep`；多次 web_search tool call 合并时按 `deep > medium > lite` 保留最高强度；不新增关键词规则和 SearchModeRouter。
- Admin Web Search 前端补齐 `glomi` provider type、展示信息、base URL 配置字段和配置状态判断；`open_url` 内容抓取 provider 保持不 seed，继续使用内置 `OnyxWebCrawler` fallback。
- 经验与坑：Glomi Gateway 是 batch query 入口，但现有 provider 多数仍是 per-query `search(query)`；实现时在 provider 抽象上加默认 `search_batch(...)` 兼容旧 provider，仅让 Glomi 走 batch，避免扩大旧 provider 行为变更。
- 错误处理补充：新增的 Glomi Search client 的 `test_connection()` 按项目新约定抛 `OnyxError`，并让 Admin web-search 测试入口保留该标准错误；旧 provider 仍沿用历史 `HTTPException` contract，未在本期扩大迁移。
- 验证记录：focused backend tests 通过 `67 passed in 4.64s`；`web` 下 `npm run types:check` 通过。前端类型检查第一次失败是本地忽略目录 `.next/dev/types` 里的旧生成文件语法损坏，`npx next typegen` 会刷新 `.next/types` 但不刷新 `.next/dev/types`，安全删除 `.next/dev/types` 后同一条 typecheck 通过。
- 新增 Search Debug Drawer 设计与计划：`docs/superpowers/specs/2026-06-15-search-debug-drawer-design.md`、`docs/superpowers/plans/2026-06-15-search-debug-drawer.md`。
- 实现聊天 timeline 内的 Search Debug Drawer：后端新增 `search_tool_debug_delta` streaming packet，`WebSearchTool` 在成功、部分失败、batch 失败时发送 provider type/name、mode、channel、queries、duration、result URLs、failed queries 和 error；前端在 Web Search 工具块 FULL 模式中默认折叠展示。
- 隐私边界：Search Debug 不落库，不新增搜索日志表，不发送 API key、Authorization header 或 Gateway base URL；`open_url` 仍使用既有 URL/documents timeline，不在本期强行和 `web_search` debug 绑定。
- Search Debug 验证记录：Glomi/Search focused backend tests `70 passed in 6.18s`；frontend focused Jest `125 passed`；`web npm run types:check` 通过。一个小坑是 Jest 运行时不做完整 TS 严格检查，`constructCurrentSearchState()` 测试需要把 test packet 显式收窄为 `SearchToolPacket[]`，否则 `tsgo` 会在 typecheck 阶段失败。
- 新增本地 Glomi Search Gateway 设计与计划：`docs/superpowers/specs/2026-06-15-local-glomi-search-gateway-design.md`、`docs/superpowers/plans/2026-06-15-local-glomi-search-gateway.md`。原因：Onyx 侧 `glomi` provider/client 已实现，但仓库里缺少可运行 Gateway；用户当前只有 Tavily API key，无法直接填给 Onyx。
- 实现本地 FastAPI Gateway：新增 `backend/onyx/search_gateway/`，提供 `GET /health` 与 `POST /search`，使用 `GLOMI_SEARCH_GATEWAY_API_KEY` 校验 Onyx 发来的 Bearer token，第一期仅支持 `channel=tavily`。
- Tavily adapter 行为：`mode=lite` 映射 Tavily `search_depth=basic`，`mode=medium` / `mode=deep` 映射 `advanced`；逐 effective query 调 Tavily，跨 query 按 URL 去重并截断到 `max_results`；响应统一成 Gateway `results`，字段包括 title/url/snippet/author/published_date。
- 配置记录：`.vscode/.env` 已把 Onyx provider 指向 `http://localhost:7777`，使用本地 `dev-gateway-key` 作为 Onyx↔Gateway token，并新增 `GLOMI_SEARCH_GATEWAY_*` 与空的 `TAVILY_API_KEY=` 占位；真实 Tavily key 只填本地 env，不进代码。
- 经验与坑：`uvicorn onyx.search_gateway.server:app` 会在模块导入时创建 app，因此不能在 import 阶段因为缺 `TAVILY_API_KEY` 直接失败；改为 `/search` 实际调用时构建 Tavily service，缺配置返回标准 `SERVICE_UNAVAILABLE`，`/health` 仍可用于确认服务进程启动。
- 基于 Genspark 对比补强本地 Gateway 研究型检索：新增 `backend/onyx/search_gateway/query_planner.py`，`mode=medium` 会把原始 query 扩成最多 5 条 source-angle query，`mode=deep` 会扩成最多 8 条；技术/项目类 query 覆盖 official docs、GitHub、changelog、benchmark/comparison，deep 额外覆盖 issues/discussions/limitations；市场类 query 覆盖 latest news、live chart、forecast，deep 额外覆盖 macro drivers、risk/support-resistance；`mode=lite` 不扩展。
- Tavily medium/deep 内容兜底：medium/deep 请求设置 `include_raw_content=true`，并让 normalized snippet 优先使用截断后的 `raw_content`；medium 截断到 800 字符，deep 截断到 1200 字符，lite 仍 `include_raw_content=false`。同时 medium/deep 的 per-query `max_results` 会拆小，避免第一个泛搜 query 吃掉所有名额，使扩展 query 真正参与召回。
- 边界记录：这次补的是 Gateway 里的“研究型检索增强”，不是完整 Genspark 式多 agent Deep Research；`open_url` 抓取 403/Playwright 失败时，medium/deep 搜索 snippet 现在能提供更强 fallback 证据，但最终高可信报告仍应优先引用成功打开/读取的页面。
- 新增搜索中档 `medium`：`WebSearchMode` 与 Gateway `SearchMode` 扩展为 `lite / medium / deep`。普通 chat 缺省仍是 `lite`，Deep Research research agent 缺省仍是 `deep`；`medium` 用于研究框架、项目、产品、公司、工具等“一次性研究型检索”，不触发完整多轮 Deep Research。
- Gateway `medium` 行为：最多 5 条 query fan-out，Tavily `search_depth=advanced`，`include_raw_content=true`，raw-content snippet 截断到 800 字符；`deep` 保持最多 8 条 query fan-out，snippet 截断到 1200 字符。多次 `web_search` tool call 合并时按 `deep > medium > lite` 保留最高搜索强度。
- Prompt / 前端同步：普通 `WEB_SEARCH_GUIDANCE` 增加 `mode=medium` 指导，Search Debug streaming type 显式允许 `medium`。文档同步更新 `docs/GlomiAI.md`、平台默认 Search Gateway spec、本地 Gateway spec 和 deep search enhancement plan。
- 新增可插拔 Search Gateway adapter 架构计划 `docs/superpowers/plans/2026-06-15-pluggable-search-gateway-adapters.md`：目标是以后接 Brave / Serper / 百度 / 搜狗 / 360 / 自研源时，只新增 Gateway adapter 和 capability declaration，不改 Onyx `web_search` 工具契约。
- Gateway 公共层拆分：新增 `backend/onyx/search_gateway/adapters.py` 与 `service.py`，把 channel registry、默认 channel、lite/medium/deep query planning、adapter capability degradation、per-query `max_results` 分配、跨 query URL 去重统一放进 `SearchGatewayService`。
- Tavily 迁移为具体 adapter：`TavilySearchAdapter` 只保留 Tavily payload、错误映射和结果 normalization；旧 `TavilySearchClient.search(request)` 保持为兼容 wrapper，内部委托 `SearchGatewayService`，避免扩大 server/test 调用面。
- Gateway server 不再在 `/search` route 里硬编码 `channel=tavily`；启动时注册 Tavily adapter，未知 channel 由公共 service 返回标准 `INVALID_INPUT`。未来 provider 切换的稳定边界是 Gateway adapter registry，而不是 Onyx provider/client。
- Capability 经验：不是所有搜索源都支持 Tavily 式 `advanced` 或 `raw_content`，所以 medium/deep 先由 service 生成统一 options，再按 adapter capability 降级；这样 Brave-like 适配器也能参与 medium/deep，只是退化为 basic/snippet-only，而不会让主链路失败。
- Adapter 架构验证记录：Gateway 单测 `18 passed`，Glomi Search client 单测 `6 passed`，`ruff check backend/onyx/search_gateway backend/tests/unit/onyx/search_gateway backend/tests/unit/onyx/tools/tool_implementations/websearch/test_glomi_search_client.py` 通过；`git diff --check` 无空白错误，仅有 Windows 工作区 LF→CRLF 提示。
- 新增实施计划 `docs/superpowers/plans/2026-06-15-open-url-fallback-and-search-benchmark.md`：先补 `open_url` snippet fallback，再提供真实 Gateway/Tavily benchmark 入口。
- 实现 `open_url` fallback：`llm_loop` 原本已经把最近 web_search 的 URL->snippet map 传给 `OpenURLTool`；现在当 indexed retrieval、crawler、link-based lookup 都失败，且失败 URL 有对应 search snippet 时，`OpenURLTool` 会返回一个明确标注为 recent `web_search` snippet fallback 的可引用 section。真实 indexed/crawled 内容始终优先，不把 snippet 冒充完整页面正文。
- 新增 open_url fallback 单测 `backend/tests/unit/onyx/tools/tool_implementations/open_url/test_open_url_snippet_fallback.py`，覆盖失败 URL 生成 fallback、已有成功 section 不重复 fallback、normalized URL 匹配。
- 新增 opt-in 真实 benchmark `backend/tests/external_dependency_unit/search_gateway/test_real_tavily_gateway_benchmark.py`：需要 `GLOMI_RUN_REAL_SEARCH_BENCHMARK=true` 和 `TAVILY_API_KEY` 才会真打 Tavily；默认 skip，避免普通外部依赖测试被网络波动拖住。
- 真实 benchmark 尝试记录：使用 `.vscode/.env` 中 Tavily key 真跑时，Tavily 连接在 TLS 阶段失败，`httpx.ConnectError: [SSL: UNEXPECTED_EOF_WHILE_READING]`；PowerShell `Invoke-WebRequest` 访问同一 endpoint 也报 SSL connection could not be established，因此当前阻塞是本机/网络到 `https://api.tavily.com/search` 的 TLS 连通性，不是 Gateway payload 或 fallback 逻辑。
- OpenURL fallback / benchmark 验证记录：完整 open_url 单测目录 `142 passed, 4 warnings`；open_url fallback + Gateway 聚焦单测 `21 passed`；open_url + Gateway + Glomi client 聚合测试 `166 passed, 4 warnings`；真实 benchmark 默认 gate 下 `2 skipped`；相关 Python ruff 通过；`git diff --check` 无空白错误，仅有 Windows LF→CRLF 提示。

## 2026-06-14

- E2 产品方向纠偏：用户明确不需要“C 端模型档位 / model catalog / user preference”，而是要“每个账户/tenant 注册即有平台默认 LLM Provider”，先只支持 OpenAI-compatible 主模型。
- 新增替代设计文档 `docs/superpowers/specs/2026-06-14-platform-default-openai-compatible-llm-design.md`：配置收敛为 `CONSUMER_DEFAULT_LLM_API_BASE`、`CONSUMER_DEFAULT_LLM_API_KEY`、`CONSUMER_DEFAULT_LLM_MODEL_NAME`，provider type 固定 `openai_compatible`，运行时回归 Onyx 原生默认模型链路。
- 将旧设计 `docs/superpowers/specs/2026-06-13-consumer-llm-provider-design.md` 标记为已被替代；同步更新 `docs/GlomiAI.md`，E2/Phase A/对话模型决策不再提 C 端模型档位。
- 新增实施计划 `docs/superpowers/plans/2026-06-14-platform-default-openai-compatible-llm.md`，拆分为单主模型 seed、运行时撤 profile override、删除 model catalog/API/UI、更新 env/docs 与验证四个任务。
- 实现 E2 纠偏：移除 C 端模型档位 catalog / preference API / 前端 selector，保留平台默认 OpenAI-compatible 主模型自动 seed。
- 配置收敛为 `CONSUMER_DEFAULT_LLM_API_BASE`、`CONSUMER_DEFAULT_LLM_API_KEY`、`CONSUMER_DEFAULT_LLM_MODEL_NAME`；provider type 固定为 `openai_compatible`，provider name 内部固定为 `Glomi Default`。
- 运行时回归 Onyx 原生默认模型链路：普通聊天、深度研究、标题生成不再强制 consumer profile；Craft 去掉 coding profile 特例，改为在原有 provider 优先级后支持已配置的 `openai_compatible` provider fallback。
- 本地 `.vscode/.env` 已更新为 `CONSUMER_DEFAULT_LLM_MODEL_NAME=qwen-plus`；该文件被 `.gitignore` 忽略，不进入提交。
- 验证记录：focused backend tests `31 passed in 2.76s`；app startup `app-ok`；frontend `npm run types:check` 通过；touched Python 文件 `ruff check` 通过；旧 `model-catalog` / `model-preference` / `ConsumerModelProfileSelector` / `consumer_model_catalog` 残留搜索无命中。
- 修复启动错误：`/model-catalog` 是 private route，但 `get_model_catalog` 缺少用户依赖，导致 `check_router_auth` 在 uvicorn 启动时抛出 `RuntimeError: Did not find user dependency in private route`。
- 变动：为 `backend/onyx/server/manage/consumer_models_api.py:get_model_catalog` 增加 `require_permission(Permission.BASIC_ACCESS)` 依赖，并新增 route auth contract 单测，确保 consumer model router 以后新增接口也会被 `check_router_auth` 捕获。
- 验证：新增单测先复现同样的 `/model-catalog` auth failure；修复后 `test_consumer_models_api.py` 通过 `5 passed`，并在 `PYTHONUTF8=1` 下构建 `onyx.main.get_application()` 通过 `app-ok`。
- 经验与坑：Windows 下直接构建 app 时可能因默认 GBK 读取 `webapp_offline.html` 出现 `UnicodeDecodeError`，验证时需要设置 `PYTHONUTF8=1`；直接 one-liner import `ee.onyx.main` 会触发 EE fallback 循环导入，不适合作为这个 auth 修复的验证入口。

## 2026-06-13

- 新增设计文档 `docs/superpowers/specs/2026-06-13-consumer-llm-provider-design.md`，记录 C 端默认 LLM Provider / Qwen OpenAI-compatible 自动初始化 / 普通用户模型档位选择的架构方案。
- 关键结论：不大改 Onyx LLM 架构，优先复用现有 `openai_compatible` provider 和 tenant 初始化 seed 流程；Provider/API key/base URL/参数策略归平台控制，C 端用户只选择平台暴露的模型档位。
- 经验与坑：Onyx 的 LLM Provider 配置跟 tenant schema 走，新注册如果创建新 tenant，默认不会继承旧账号手动配置；需要在 tenant setup 中做幂等 seed，或通过同步任务补齐已有 tenant。
- 实现进展：新增 consumer model catalog（快速/均衡/深度/编程/多模态）、Qwen OpenAI-compatible env 配置、幂等 provider seed、`/api/model-catalog` 与 `/api/user/model-preference`，并把 App/NRF 主模型选择入口改成 C 端模型档位 selector。
- 测试记录：后端 focused tests 覆盖 catalog fallback、seed request/默认模型设置、API 偏好保存、单租户与多租户 setup hook；前端增加 consumer catalog 工具函数测试，并跑过 `npm run types:check`。
- 经验与坑：前端 profile API 不返回 key/base URL/provider id；选择档位后通过后端写入既有 `User.default_model`，再刷新 `/api/me` 让 `useLlmManager` 复用旧解析链路，避免新增一套聊天模型解析机制。
- 新增设计文档 `docs/superpowers/specs/2026-06-13-agent-search-and-research-strategy-design.md`，将 E3 默认超级对话调优、E4 深度研究中文化、Agent 搜索方法论合并为“中文 Agent 搜索与研究能力层”。
- 关键结论：不要把普通对话搜索和深度研究做成两套系统；两者共享 Search Cognition Loop（何时搜索、问题拆解、query portfolio、来源路由、串并行策略、证据评估、Evidence Pack），普通对话走轻量模式，深度研究走重型模式。
- 产品路线同步：`docs/GlomiAI.md` 已更新 E3/E4 表述，把普通对话轻量搜索、深度研究中文报告、中文 benchmark 都归入 Phase A 核心能力验证；E13 superagent 继续作为 Phase B 增强，未来复用这层搜索型能力。
- 经验与坑：Onyx 已有 `llm_loop` 与 `dr_loop` 两条成熟执行链，第一期不应重写 runtime；应先通过 playbook、prompt、tool guidance 和中文 benchmark 验证搜索/研究质量，再决定是否引入结构化 `SearchIntent` / `SearchPlan` / `EvidencePack` 对象。
- 新增实施计划 `docs/superpowers/plans/2026-06-13-agent-search-and-research-strategy.md`，将“中文 Agent 搜索与研究能力层”Phase 1 拆成共享 search strategy playbook、普通 chat tool guidance、deep research planner/orchestrator/research-agent prompt、中文 benchmark、验证与记录六个可执行任务。
- 计划自审结论：当前实施范围只做 prompt / playbook / benchmark，不改 `llm_loop` / `dr_loop` runtime；已核对现有 prompt 常量与 `.format(...)` 调用点，后续实现时重点避免新增未转义 `{}` 破坏 prompt formatting。
- 继续实现 `2026-06-13-consumer-llm-provider-design.md`：补齐 Phase 3 的最小场景化策略，普通聊天在无显式 override 时按用户 consumer profile 解析，deep research 强制走 `deep`，聊天标题命名优先 `fast`，Craft session 默认优先 Qwen `coding` profile。
- 修复一个关键兼容坑：前端 `LlmDescriptor.provider` 使用 provider type（如 `openai_compatible`），但后端 `LLMOverride.model_provider` 原路径按 provider name 查；新增 provider type + model fallback，避免 Qwen profile 选择后因找不到名为 `openai_compatible` 的 provider 而退回默认模型。
- 错误处理补充：`/api/model-catalog` 在 C 端默认模型未启用或缺少 `CONSUMER_DEFAULT_LLM_API_KEY` 时返回 `SERVICE_UNAVAILABLE`，前端 selector 显示“模型服务暂不可用”，不泄露 key/base URL 等配置细节。
- 测试/验证坑：`backend/tests/unit/onyx/llm/conftest.py` 会加载 LiteLLM model metadata enrichments，在当前受限网络/Windows 环境下 pytest 可能挂住；consumer catalog/factory 纯单测已迁到 `backend/tests/unit/onyx/`，避开不需要的目录级 fixture。
- 最新验证：consumer/Qwen focused backend tests 21 个通过；consumer frontend Jest 3 个通过；`npm run types:check` 通过；touched Python 文件 `ruff check` 通过。
## 2026-06-13 - Shared search strategy playbook

- Added `backend/onyx/prompts/search_strategy.py` with reusable search, query portfolio, source routing, evidence evaluation, open URL, and deep research report guidance constants for Phase 1 agent search/research prompts.
- Added `backend/tests/unit/onyx/prompts/test_search_strategy.py` to lock required bilingual search, source authority, conflict handling, Evidence Pack, and Chinese report expectations.
- Noted and fixed test/playbook wording mismatches by explicitly naming the `Freshness` and `中文` decision points in chat search guidance.
- Verification note: bare `pytest` was not available on PowerShell PATH, so targeted tests were run with `.venv\Scripts\python.exe -m pytest`.

## 2026-06-13 - Chat tool search strategy wiring

- Wired ordinary chat tool guidance in `backend/onyx/prompts/tool_prompts.py` to reuse shared search strategy constants for search intent, query portfolio, source routing, evidence evaluation, and open_url evidence reading.
- Added focused prompt tests in `backend/tests/unit/onyx/prompts/test_tool_prompts.py` to lock the new strategy markers and verify `WEB_SEARCH_GUIDANCE.format(site_colon_disabled=...)` remains valid.
- Verification note: bare `pytest` was unavailable on PowerShell PATH; targeted prompt tests were run with `.venv\Scripts\python.exe -m pytest`.

## 2026-06-13 - 中文 Agent 搜索与研究能力层 Phase 1

- 实现进展：完成 `docs/superpowers/plans/2026-06-13-agent-search-and-research-strategy.md` 的 Phase 1，新增共享 search strategy playbook，并把普通 chat tool guidance、deep research planner/orchestrator/research-agent/final-report prompts 统一到同一套搜索方法论。
- 深度研究中文化：`backend/onyx/prompts/deep_research/orchestration_layer.py` 现在显式要求围绕 information gaps 做研究计划、按独立证据维度编排 research_agent、最终报告使用自然中文结构并保留证据冲突与不确定性。
- Research agent 调优：`backend/onyx/prompts/deep_research/dr_tool_prompts.py` 与 `research_agent.py` 已加入 query portfolio、source routing、open_url evidence reading、Evidence Pack、source context/confidence/conflicts/remaining gaps 等规则。
- Benchmark：新增 `backend/onyx/evals/glomi_search_research_benchmark.py`，固定 20 条中文 benchmark case，覆盖 `chat_lite` / `deep_research` 两个 profile，以及最新事实、政策、产品对比、技术研究、市场研究、消费决策、事实核查、公司研究等 category。
- 测试记录：focused prompt/eval tests 通过 `22 passed in 0.08s`；目录级 `backend/tests/unit/onyx/prompts backend/tests/unit/onyx/evals` 通过 `24 passed in 0.43s`。Windows 环境 bare `pytest` 不在 PATH，统一使用 `.venv\Scripts\python.exe -m pytest`。
- 经验与坑：prompt 常量会被 `.format(...)` 或 f-string 组合，后续新增 `{}` 需特别小心；本期仍不改 `llm_loop` / `dr_loop` runtime，下一步应先用真实 Qwen/DeepSeek/Kimi 跑 benchmark，再决定是否进入结构化 `SearchIntent` / `SearchPlan` / `EvidencePack`。
- Review 备注：最终代码审查通过，无 Critical/Important 问题；仅发现历史遗留的 deep research tool prompt 中 `open_urls` / `open_url` 名称混用，建议后续单独做 prompt cleanup，不在本期扩大范围。
