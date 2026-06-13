# 所有相关的变动都需要记录在summary.md中，包括坑，经验，变动等等；关于产品相关的文档在docs/GlomiAI.md，有产品相关变动了需要同步更新这个文件

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
