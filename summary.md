# 所有相关的变动都需要记录在summary.md中，包括坑，经验，变动等等；关于产品相关的文档在docs/GlomiAI.md，有产品相关变动了需要同步更新这个文件

## 2026-06-16

- 产品路线切换记录：用户确认 Phase A 核心能力已经验证完成，当前正式进入 Phase B，开始把 Craft 作为 GlomiAI 的生成交付运行时来集成和改造。
- 同步更新 `docs/GlomiAI.md`：把状态从“验证期当前唯一重心”调整为“Phase A 已完成，Phase B/Craft 当前重心”；新增 Craft 集成/改造路线 B0-B4，明确先做稳定运行与资源治理，再做独立 Craft C 端入口、生成物分享、主对话派发和超级编排增强。
- 同步更新 `README.md`：当前阶段改为 Phase B Craft 王牌能力启动；分支状态表对齐平台模型目录、中文对话/深度研究已验证，并新增 Craft 生成交付运行时章节，强调短问答/研究不进重型 sandbox，需要页面/PPT/看板/小工具/可分享成品时才派发 Craft。
- 决策经验：前一阶段对 Craft “太重”的担心仍成立，但 Phase B 不是绕开 Craft，而是把资源治理当成第一优先级；最大化发挥 Craft 的方式是保留 sandbox、实时预览、文件系统、快照、skills、approvals 等强项，同时改入口、控并发、做分享闭环，并让主控只在生成交付场景派发 Craft。
- 本地 Docker Compose 升级执行：使用 `docker compose -f docker-compose.yml -f docker-compose.craft.yml build api_server web_server` 重建本地 `glomi-onyx-backend:local` / `glomi-onyx-web-server:local`，随后依次强制重建 `api_server`、`background`、`search_gateway`、`sandbox-proxy`、`web_server`；`api_server` 启动时已执行 Alembic `01c63968ff8f -> 2aedcb0ff5fd`，数据库 `alembic_version=2aedcb0ff5fd` 且 `chat_run_event` 表存在，`http://localhost:3001/` 返回 200。
- Craft 模型继承修复：遇到 `Model not found: openai/codex-auto-review`，根因是 OpenAI-compatible 动态 provider 的自动同步模型列表把 `codex-auto-review` 排在首位，Craft 预创建 sandbox 时没有用户显式选择模型，后端默认落到该模型；同时 OpenCode 对 OpenAI-compatible 自定义 API base 仍会用内置 OpenAI 模型目录校验，未显式声明的平台模型会被拦截。修复为后端对 `openai_compatible` 优先选择 Glomi Craft 模型（`gpt-5.5` 等），并在 `opencode.json` 的 `openai` provider block 显式合并声明同一 API base 下所有可见 OpenAI-compatible 模型，支持后续 per-message 模型 override 到 Qwen/DeepSeek/GLM。已重建后端镜像并重启 `api_server`、`background`、`search_gateway`、`sandbox-proxy`；旧 `sandbox-c24ef204` 已删除并把 sandbox 状态置为 `TERMINATED`，历史 `codex-auto-review` build_session 记录已改回 `gpt-5.5`，避免继续使用旧 `openai/codex-auto-review` 配置。
- Next 16 构建兼容坑：生产构建会校验 App Router page/route export。修复 `web/src/app/app/shared/[chatId]/page.tsx` 中非页面 API 的 `constructMiniFiedPersona` 命名导出；修复 `web/src/app/mcp/[[...path]]/route.ts` route context 类型，把 `params` 改为必有 `Promise<{ path?: string[] }>`，否则 `next build --webpack` 在类型检查阶段失败。
- Docker Compose 服务重建坑：强制重建 `api_server` 后容器 IP 会变化，已有 `nginx` 仍可能持有旧 upstream IP，页面表现为静态资源可加载但 `/api/*` 502/“服务端不可用”，nginx 日志显示 `connect() failed (111: Connection refused) upstream: http://旧IP:8080/...`。处理方式是同步重建/重启 `nginx`，本次重启后 `http://localhost:3001/api/health` 返回 ok。
- Craft provisioning 失败排查：手工修历史 `build_session` 时误把 SQLAlchemy Enum 状态写成小写 `active`，导致接口报 `LookupError: 'active' is not among the defined enum values. Possible values: ACTIVE, IDLE`，前端表现为 `Failed to provision sandbox` / 发送按钮转圈。已把历史记录修回 `ACTIVE`。同时前端 Craft 模型选择器也补齐 OpenAI-compatible 的 Glomi 模型优先级，避免页面默认继续显示 `codex-auto-review`；重建 `web_server` 并重启 `nginx`。
- Docker web 镜像构建补充：Next 16.2.6 默认 Turbopack 在 Docker `next build` 阶段约 555 秒后可能触发内部超时 `failed to receive message / deadline has elapsed`；构建命令改为显式 `next build --webpack`，保留生产构建能力并避开 Turbopack worker 超时。
- Craft 远端调试路径确认：本机继续源码启动前端/后端/Search Gateway，Craft 依赖放到远端 Docker Compose；远端已启动 `onyx-sandbox-proxy-1`、`docker-compose.craft.yml`、`onyxdotapp/sandbox:v0.1.52`、`onyx_craft_sandbox` 网络和 `sandbox_proxy_ca` volume。该模式适合小本机开发，避免本地跑 k8s/sandbox 吃满资源。
- Craft `LLM Provider Required` 根因：Craft 前后端原来只把 `anthropic` / `openai` / `openrouter` 当作 Build 支持 provider，Glomi 平台默认模型目录使用 `openai_compatible`，所以普通 chat 可用但 Craft onboarding 会拦住非管理员/普通用户。
- Craft OpenAI-compatible 二开：前端 onboarding/model picker 纳入 `openai_compatible`；后端 Build provider 查询允许可访问的 `openai_compatible`；沙箱 OpenCode 边界把 Onyx 的 `openai_compatible` 映射为 OpenCode 识别的 `openai` provider，并保留自定义 `api_base/api_key`，从而可让 GPT-5.5、GLM-5.2、Qwen3.7 Plus 等平台 OpenAI-compatible 模型进入 Craft。
- Craft 沙箱配置经验：如果同时存在 first-party `openai` 与 `openai_compatible`，两者在 OpenCode 侧都会渲染为 `openai`，因此配置生成时按调用顺序去重，保留默认/首选 provider，避免同一个 OpenCode provider block 被覆盖。
- Craft 验证记录：前端 `bun test src/app/craft/onboarding/__tests__/constants.test.ts` 通过 `10 pass`；后端 `.venv\Scripts\python.exe -m pytest -q backend/tests/unit/onyx/server/features/build/sandbox/test_opencode_config.py backend/tests/unit/onyx/server/features/build/session/test_get_all_build_mode_llm_configs.py backend/tests/unit/onyx/server/features/build/sandbox/test_send_message_with_bus.py` 通过 `55 passed`；`git diff --check` 无空白错误，仅有 Windows LF→CRLF 提示。外部依赖测试 `.venv\Scripts\python.exe -m pytest -q backend/tests/external_dependency_unit/craft/test_build_llm_provider_access.py` 在 setup 阶段因本机 `127.0.0.1:5432` Postgres 连接被拒绝失败，属于本地依赖环境限制，不是新增断言失败。
- 实施 Phase A 模型目录与刷新恢复：平台模型目录 seed GPT-5.5、Qwen3.7 Plus、DeepSeek V4 Pro、GLM-5.2，并把图片/深思/研究/代码等能力由后端 `/api/chat/available-models` 返回给前端模型选择器。
- 图片上传能力改为信任后端 `supports_image_input`：GPT-5.5 / Qwen3.7 Plus 可作为视觉主力模型，DeepSeek V4 Pro / GLM-5.2 暂不支持图片时前端给中文提示，不再只靠前端硬编码判断。
- 回答形态策略落地到普通 chat prompt：明确 direct_answer / focused_brief / deep_report，默认研究型普通回答走 focused_brief，避免把“搜索更深”误解成“回答更长”。
- 新增轻量 `chat_run` / `chat_run_event` 持久化：流式回答创建 run，逐 packet 落库，完成/失败/取消时标记状态；`get-chat-session` 返回 `active_run`，`/api/chat/resume-chat-run` 可按 run_id 回放已存事件。
- 前端会话加载接入 active run replay：F5 后若后端返回 running run，前端会请求 resume、把已落库 packet 合并回 assistant message，并保持 streaming 状态直到看到 stop/error；本期是 Phase A 事件重放，实时追尾后续可再抽共用 packet handler 或加 Redis/pubsub。
- 经验与坑：后端 run 只能在 `build_chat_turn` 创建好 user/assistant message 后创建，因此最早的 session/message id metadata packet 不进入 run_event；恢复依赖 `active_run.assistant_message_id` 定位消息。前端 `BackendMessage` 也有 `error` 字段，不能用 `"error" in packet` 粗略判断 StreamingError，已补 `isStreamingErrorPart` type guard。
- 验证记录：后端 focused tests `.venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\db\test_glomi_model_catalog.py backend\tests\unit\onyx\db\test_chat_run.py backend\tests\unit\onyx\prompts backend\tests\unit\onyx\server\query_and_chat backend\tests\unit\onyx\chat\test_resumable_chat_run.py -xv` 通过 `36 passed`；后端 ruff 通过；前端 `npm test -- chatAvailableModels.test.ts resumeChatRun.test.ts` 通过 `2 passed / 3 tests`；`npm run types:check` 通过；`npm run lint` 通过。
- 手工验证记录：启动 `web` 的 Next dev server 后 `http://localhost:3000` 返回 200，Playwright 打开页面标题为 `Glomi AI`；页面显示“后端仍在启动”提示，因此本轮未完成登录、模型选择、图片粘贴和真实 F5 恢复的端到端手工流程。

- 新增总设计文档 `docs/superpowers/specs/2026-06-16-resumable-runs-model-strategy-answer-policy-design.md`，把 5 个产品/架构问题合并为 Phase A 设计：聊天运行态刷新恢复、模型角色与厂商能力画像、回答长度自适应、图片/文档输入能力、平台多模型目录与前端模型选择器。
- 刷新恢复决策：第一阶段不直接建设完整超级智能体 Task/Run DAG，而是在现有 chat streaming 外加轻量 `chat_run` / `chat_run_event` 层；F5 后可通过 `run_id + event_seq` replay 已有 packet 并继续订阅后续流式进度。
- 模型策略决策：不把 `low / medium / high` reasoning 暴露给用户，也不把它当跨厂商通用语义；内部使用 Glomi 模型角色（fast / balanced / reasoning / research / vision / coding）和 provider capability profile，再由后端按 OpenAI、DeepSeek、Qwen、GLM 的实际能力映射。
- 默认模型目录决策：从“每账户 seed 一个默认模型”升级为平台内置 Glomi Model Catalog。前期默认开放 GPT-5.5、Qwen3.7 Plus、DeepSeek V4 Pro、GLM-5.2；已有账户通过幂等 sync 补齐缺失 provider/model，不覆盖用户已选模型和管理员手动凭据。
- 视觉能力决策：前端不硬编码模型名判断图片能力，只消费后端返回的 `supports_image_input`；GPT-5.5 与 Qwen3.7 Plus 默认支持图片，DeepSeek V4 Pro 与 GLM-5.2 默认不支持图片。选择支持图片的模型时允许粘贴/拖拽/上传图片，不支持时给温和提示。
- 回答策略决策：普通 chat 默认根据问题自动选择 direct_answer / focused_brief / deep_report；搜索深度不等于回答长度，研究型普通回答优先让用户抓住判断、证据强弱和下一步，完整长报告只在用户明确要求或 Deep Research 中输出。
- 同步更新 `docs/GlomiAI.md`：E2 从“平台默认单 OpenAI-compatible 主模型”调整为“平台模型目录与模型选择”；Phase A 纳入刷新恢复、图片输入能力、后端模型能力画像和已有账户模型同步。

## 2026-06-15

- 本地 Docker Compose 启动记录：当前机器已有 Langfuse 占用 `3000/5432/6379/9000`，且 `80` 也已被占用；因此满血 Docker Compose 不叠加 `docker-compose.dev.yml` 暴露依赖端口，只通过 nginx 暴露应用，并在 `deployment/docker_compose/.env` 设置 `HOST_PORT_80=8081`、`HOST_PORT=3001`。
- Docker web 镜像构建坑：`bun install --frozen-lockfile` 在 Docker build 中使用默认 `--network-concurrency=48` 时多次下载到损坏 tarball，表现为不同包随机 `Integrity check failed for tarball`；本地改为较低的 `--network-concurrency=4 --no-progress` 并把当前 compose `.env` 的 `BUN_CONFIG_REGISTRY` 切到 `https://registry.npmjs.org`，优先保证可重复构建。
- 本地满血 Docker Compose 已拉起：使用 `docker compose --profile s3-filestore up -d --no-build --wait` 启动 `api_server`、`web_server`、`search_gateway`、`background`、Postgres、Redis、OpenSearch、MinIO、inference/indexing model server、code-interpreter、nginx，最终 `13/13` healthy；验证 `http://localhost:3001` 返回 200、`/api/health` 正常，api 容器内访问 `http://search_gateway:7777/health` 返回 `{"status":"ok","channel":"tavily"}`。
- 满血 Docker Compose 纳入 Glomi Search Gateway：`deployment/docker_compose/docker-compose.yml` 和 `docker-compose.prod.yml` 新增 `search_gateway` 服务，复用 backend 镜像运行 `uvicorn onyx.search_gateway.server:app --host 0.0.0.0 --port 7777`，不暴露公网端口，由 `api_server` 在 compose 内网访问。
- Docker env 模板补齐 Glomi 默认能力配置：`env.template` / `env.prod.template` 新增 `CONSUMER_DEFAULT_LLM_*` 示例、`GLOMI_DEFAULT_WEB_SEARCH_API_BASE=http://search_gateway:7777`、Gateway bearer token 和 `TAVILY_API_KEY` 占位；README 补充 Docker 内部使用 `search_gateway:7777`，只有本地源码直跑才使用 `localhost:7777`。
- 新增 compose 回归测试 `backend/tests/unit/deployment/test_glomi_search_gateway_compose.py`，覆盖主 compose/prod compose 都包含内部 `search_gateway`、不暴露 ports、API 依赖 Gateway，以及 env 模板指向 compose 内部 Gateway。验证记录：新增测试 4 passed；`docker compose -f docker-compose.yml config --quiet` 通过；`docker-compose.prod.yml` 在临时空 `.env.nginx` 下 config 通过，只有既有 `USE_IAM_AUTH` 未设置 warning。
- 新增普通 chat 研究型回答策略设计 `docs/superpowers/specs/2026-06-15-ordinary-chat-research-answer-policy-design.md`：问题根因不是搜索不足，而是普通对话缺少“搜索后如何克制表达”的策略，导致调研/横评类问题容易输出几千到上万字，用户抓不到重点且难以评估质量。
- 实现 Ordinary Chat Research Answer Policy：在 `backend/onyx/prompts/search_strategy.py` 新增 `CHAT_RESEARCH_ANSWER_GUIDANCE`，并接入 `TOOL_DESCRIPTION_SEARCH_GUIDANCE`。策略明确普通 chat 不使用固定模板，由 Agent 自适应选择回答形态；默认优先综合判断和证据强弱，不逐条搬运搜索材料；`deep search` 只表示证据收集更深，不等于最终回答更长；只有用户明确要求完整报告/详细展开/文档式交付时才输出长篇。
- 同步更新 `docs/GlomiAI.md`：E3 超级对话调优加入“普通 chat 研究型回答自适应但克制”的产品边界，区分搜索强度和回答长度，Deep Research 长报告预期保持不变。
- 重新生成顶层 `README.md`：从上游 Onyx 项目介绍切换为 GlomiAI 中文主 README，围绕 C 端消费级超级 Agent 定位、Phase A 核心能力验证、平台默认 OpenAI-compatible LLM、Glomi Search Gateway、Search Debug Drawer、本地开发/验证命令和开发约束重组；保留 Onyx/MIT 来源与正式发布前需复核授权边界的提醒。
- 完善顶层 `README.md`：新增当前分支状态表，明确 E1/E2/E3/E4、Glomi Search Gateway、adapter 架构、Search Debug Drawer、Craft/E13/商业化模块的已做与待做；补充平台默认 LLM seed、中文搜索/研究方法论、`web_search` lite/medium/deep、Gateway adapter service、Search Debug streaming packet 的逻辑链路说明。
- 应用 `web/src/assets/brand` 品牌资源：新增透明派生图 `logo-mark.png` 与 `wordmark.png`，`GlomiLogoMark` 从 CSS 字母 G 改为渲染真实 Glomi 图标，登录/注册容器与错误页也改为复用同一品牌组件；默认 favicon 从旧 `onyx.ico` 改为 `/logo.png`，并同步覆盖 `web/public/logo*.png` / `logotype*.png`。
- 品牌资源经验：用户提供的原始 PNG 是 RGB 白底/棋盘底，不是透明 PNG；直接用于深色/非白背景会露出画布，因此生成只移除边缘背景的透明派生图，保留图标内部白色笔画和橙色光点。
- 品牌资源补救：按用户反馈改为使用 `brand.png` 派生横向 `wordmark.png`，`GlomiLogotype` 直接渲染该 wordmark，不再用图标+文本拼接；默认助手 `AgentAvatar` 的旧黑圆 G 也改成 `GlomiLogoMark`，已用 `vayneyy@gmail.com` 测试账号登录并在“聊天总结”会话确认无旧 G 节点残留。
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
- 2026-06-15 Docker 部署构建坑：前端镜像在 `RUN bun install --frozen-lockfile` 阶段可能因 Docker build 环境访问 npm registry 不稳定报 `ConnectionClosed downloading tarball`。主机能访问外网不代表 build 容器继承主机 npm 配置；此前建议写 `web/.npmrc` 也不够，因为 Dockerfile 在 `bun install` 前没有复制 `.npmrc`。
- 修复：`web/Dockerfile` 新增 `BUN_CONFIG_REGISTRY` build arg，构建时写入 `$HOME/.bunfig.toml` 的 `[install].registry` 后再执行 `bun install`；所有定义前端 build args 的 Docker Compose 文件传入该 build arg，env 模板增加 `BUN_CONFIG_REGISTRY=https://registry.npmmirror.com` 示例。
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

## 2026-06-16 - Mini host service restart memory pressure investigation

- 现象分析：重启后 Docker 同时拉起 Onyx + Langfuse + sandbox，14GiB 内存机器在启动窗口只剩约 320MiB free；虽然 `available` 约 4GiB、swap 基本未用，瞬时启动峰值和 CPU/IO 抢占足以导致桌面/ssh 卡死。
- 主要内存占用：Onyx OpenSearch 约 2.7-2.9GiB RSS（compose 配置 `OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g` 且 `AlwaysPreTouch`），Onyx background/supervisord/celery 约 2.2GiB，Langfuse stack 合计约 2.6GiB（web/worker/clickhouse/minio 等）。
- 已执行止血：停止可选 Langfuse compose stack，并停止当前一次性 `sandbox-c24ef204` 容器；停止后内存从约 10GiB used / 320MiB free 改善到约 9.1GiB used / 2.1GiB free、available 约 5.8GiB。
- 经验与建议：开发机上 Langfuse 属于可选 tracing/observability，不需要时不要随系统/批量重启一起启动；Onyx core 保留 relational_db/cache/opensearch/api_server/web_server/nginx/background/search/model servers。若仍卡顿，下一步优先考虑禁用 Craft sandbox/code-interpreter 或降低 OpenSearch heap/给容器加 memory limit。

## 2026-06-16 - Disable Langfuse autostart

- 将 `/home/shiyi/langfuse/docker-compose.yml` 中 6 个 Langfuse 服务的 `restart: always` 改为 `restart: "no"`，避免 Docker daemon / 系统重启后自动拉起 Langfuse stack。
- 同步对现有容器执行 `docker update --restart=no`，已验证 `langfuse-web/worker/postgres/redis/clickhouse/minio` 的 RestartPolicy 均为 `no`，当前均处于 Exited 状态。
- 后续如果需要临时使用 Langfuse，可手动执行 `cd /home/shiyi/langfuse && docker compose up -d`；用完建议 `docker compose stop`。

## 2026-06-16 - Additional restart safety tuning

- 当前 Onyx-only 状态内存约 9.1GiB used / 2.0GiB free / 5.8GiB available，Langfuse 已不再自启，SSH 进程已有 `oom_score_adj=-1000` 保护，明确 OOM 杀 SSH 的风险较低。
- 为降低后续系统/服务重启瞬时内存峰值，将 `deployment/docker_compose/docker-compose.yml` 里的 OpenSearch heap 从 `-Xms2g -Xmx2g` 下调到 `-Xms1g -Xmx1g`。注意：需要下次 recreate OpenSearch 容器后生效；当前运行中的 OpenSearch 仍是旧 heap。
- 进一步保险建议：系统层面把 swap 从 4G 扩到 8G/16G，但当前 sudo 需要密码，未自动执行；如后续仍卡顿，可手动扩容 swap 或继续禁用 Craft/code-interpreter 等可选服务。

## 2026-06-16 - Rebuild and restart Onyx services

- 按要求重新 build/recreate Onyx：完整 build 时 backend/web 使用缓存并成功产出 `glomi-onyx-backend:local` 与 `glomi-onyx-web-server:local`；model-server 本地 build 因需要下载大量 CUDA/Torch 依赖超过 15 分钟 timeout，后续改用已有 `onyxdotapp/onyx-model-server:latest` 镜像执行 `docker compose up -d --no-build --force-recreate --wait`。
- Onyx compose 服务已全部重建并 healthy：api_server/background/web_server/nginx/search_gateway/sandbox-proxy/model servers/postgres/redis/opensearch/code-interpreter 均启动；`http://localhost:3001/` 与 `http://localhost:8081/api/health` 返回 200。
- OpenSearch 新容器已确认使用 `OPENSEARCH_JAVA_OPTS=-Xms1g -Xmx1g`，当前内存约 1.8GiB，比之前约 2.8GiB 明显降低。
- Langfuse 容器保持 Exited，不参与本次重启；当前系统约 9.0GiB used / 1.8GiB free / 5.9GiB available，swap 已扩到约 15GiB，重启抗压能力更好。
- 注意：当前仍有 `sandbox-c24ef204` 运行并占用约 1.25GiB/2GiB；如果后续不需要该 sandbox，可停止以释放更多内存。

## 2026-06-16 - Craft sandbox session initialization failure

- 排查 `/api/build/sessions` 500：api_server 日志显示 build session 创建后在写入 sandbox workspace 时失败，核心错误是 `mktemp: failed to create directory via template '/workspace/managed/tmp.XXXXXXXXXX': Permission denied`，随后 `ensure_opencode_session` 超时。
- 复现定位：在 sandbox 容器中 `uid=1000(sandbox)` 可写 `/workspace/managed`，但 `uid=1001` 写入会 Permission denied；Docker exec 从 api_server 内部发起时在当前环境可能默认成调用方 UID 1001，而不是 sandbox 用户。
- 修复：`DockerSandboxManager.write_files_to_sandbox` 调用 `stream_stdin_to_container` 时显式指定 `user="1000:1000"`，确保原子写入 skills/user-library/session 文件时使用 sandbox workspace owner，避免权限漂移。
- 部署动作：已 rebuild backend 镜像并 recreate `api_server/background/search_gateway/sandbox-proxy`；随后停止并移除旧的 `sandbox-c24ef204`，让下一次创建 Build session 时重新 provision 干净 sandbox，避免复用已卡住/权限状态异常的旧容器。
- 后端 502 复盘：api_server 本身 healthy，但 recreate api 后 nginx 仍缓存旧 upstream IP（日志 `connect() failed ... upstream: http://172.19.0.12:8080`，新 api IP 为 `172.19.0.11`），导致 `/api/*` 经 nginx 返回 502。已 `--force-recreate --no-deps nginx` 刷新 upstream，`/api/health` 在 3001/8081 均恢复 200。

## 2026-06-16 - Craft long-task stream_read_error mitigation

- 新问题：PPT 生成任务已进入 sandbox 并成功执行到 `mkdir outputs/ppt`，说明 sandbox 初始化/权限问题已解决；失败点变为 OpenCode 调用平台 LLM 时 `upstream_error/stream_read_error`，sandbox 日志显示 `providerID=openai modelID=gpt-5.5`，约 95 秒后上游流断开。
- 处理策略：Craft 长任务优先切到更适合中文长输出且更稳定的 `qwen3.7-plus`；backend 与 frontend 的 OpenAI-compatible Craft 模型优先级均改为 `qwen3.7-plus -> glm-5.2 -> gpt-5.5 -> deepseek-v4-pro`，并把本地 compose 默认模型从 `gpt-5.5` 改为 `qwen3.7-plus`。
- 经验：这次不是 nginx/backend/sandbox 初始化不可用，而是 LLM 上游流式响应中断；前端显示为任务中断，后端 `serve_transport` 看到 `GeneratorExit` 是客户端/上游错误后的清理结果。
- 用户确认当前 `qwen3.7-plus` 路由不通，因此撤回刚才的 Craft 默认切 Qwen 操作：backend/frontend Craft 优先级与 compose 默认模型恢复为 `gpt-5.5`。后续应先排查 `gpt-5.5` 长流中断或选择其它已验证可用模型，不直接切 Qwen。
- 模型目录调整为后端控制的供应商分组结构：GPT 供应商继续使用既有 `CONSUMER_DEFAULT_LLM_*` OpenAI-compatible gateway，MiniMax 供应商新增 `GLOMI_MINIMAX_LLM_*` 官方 endpoint/key 配置（默认模型 `MiniMax-M3`）。`/api/chat/available-models` 新增 `supplier_id` / `supplier_display_name`，前端模型选择器优先按后端供应商字段分组，避免把 GPT 和 MiniMax 都折叠进同一个 `openai_compatible` 组；文档与 env 模板已同步。
