# 设计文档：基于 Onyx 二开「Glomi AI」—— 战略定位 + 第一个 spec（汉化 + UI 资源替换）

- **日期**：2026-06-12
- **品牌**：Glomi AI（暂无中文名，UI 统一用 "Glomi AI"；slogan 待定，记为 `<SLOGAN_TBD>`）
- **底座**：fork 自 [onyx-dot-app/onyx](https://github.com/onyx-dot-app/onyx)
- **本仓库**：`d:\dev\agent\glomi-ai`

---

## Part A — 战略上下文（决策依据，非本 spec 的实施范围）

### A.1 产品定位
**C 端消费级超级 Agent**（对标 Genspark）。个人用户、深度研究 / 生成成品（PPT/网站/数据/应用）、强调消费级 UX。Onyx 的企业 RAG / 连接器 / admin 退居二线，**底层引擎是要死守的核心**，前台重塑成消费级体验。

### A.2 Fork 策略：硬 fork
后端由我方自行接管，**不合并上游 Onyx 更新**，所有改动只在本 fork 分支。

- **收益**：最大改造自由度；汉化可激进抽取全部字符串，不必顾忌与上游的 diff。
- **代价（已知并接受）**：Onyx 引擎进化（深度研究 / agent loop 优化）、安全补丁、bug 修复，全部由我方自行维护。

### A.3 License 边界（商用合规，重要）
Onyx 是双层授权：

- **根目录 MIT**：自由商用。本项目要用的 Agent 引擎链路全部在此层。
- **所有 `ee/` 目录 = Onyx Enterprise License**：生产环境商用**必须购买 Onyx 企业授权**，仅开发/测试免费。涉及目录：
  - 后端：`backend/ee/`（`billing`、`analytics`、`license`、`enterprise_settings` 白标、企业 `auth`/SSO/SAML、`external_permissions` 权限同步）
  - 前端：`web/src/app/ee/`（`admin`、`agents` 企业版管理 UI）、`web/src/ee/`

**决策**：`ee/` 整块**剥离重建**——C 端本就需要换成自己的能力（微信/手机号登录、微信支付、自有用量统计）。Agent 引擎本体（`backend/onyx/db/persona.py` + `server/features/persona`）是 MIT，可自由商用。

### A.4 能力地图（保留 / 弱化 / 剥离）

| 模块 | 代码位置 | 处置 | 说明 |
|---|---|---|---|
| Agent loop（自研 tool-calling 循环，**非 LangGraph**） | `backend/onyx/chat/llm_loop.py`、`llm_step.py` | ✅ 死守 | 支持 native + **XML 式 tool call**，兼容不支持原生函数调用的国产模型 |
| 深度研究（orchestrator 多轮） | `backend/onyx/deep_research/dr_loop.py` | ✅ 死守 + 加强 | 计划 → 子研究 agent → think → 报告 |
| Craft（沙箱内端到端生成交付物） | `backend/onyx/server/features/build/*` | ✅ 死守，做主打 | Genspark 式「生成网站/PPT/数据/应用」本体 |
| 工具体系 | `backend/onyx/tools/tool_implementations/*` | ✅ 保留 | bash/python/web_search/image_gen/memory/open_url/kg |
| 长期记忆 | `backend/onyx/db/memory.py` | ✅ 保留 | C 端黏性 |
| Persona/Assistant（「Agents」） | `backend/onyx/db/persona.py`、`server/features/persona` | ✅ 保留，简化 | MIT 可商用；C 端做成「预置智能体/角色」 |
| Skills + MCP（client & server） | `backend/onyx/skills/*`、`mcp_server/` | ✅ 保留 | 后期接国产工具生态 |
| 50+ 西方连接器 | `backend/onyx/connectors/*` | 🟡 缓，按需 | C 端初期用不上；后期只接飞书/钉钉/语雀等 |
| 企业 admin / RBAC / 多租户 | `server/manage`、admin UI | 🟡 弱化 | C 端不需要复杂企业配置 |
| `ee/` 全家桶 | `backend/ee/*`、`web/src/*/ee/*` | ❌ 剥离重建 | EE 授权 + C 端要换成自有能力 |

**要自建/加强的「中国化外壳」**：① i18n（不存在）② 国产模型默认接入（DeepSeek/Qwen/智谱 logo 已在 `web/public/`）③ 微信/手机号登录 + 微信支付 ④ 国产连接器 ⑤ 品牌与合规（ICP 备案、内容安全）⑥ C 端消费级 UI 重塑。

### A.5 Agents 引擎深度解读（已读真实代码）
1. **一个 Agent = 一个 `Persona`**（`db/persona.py`）：配置包，捆绑 system prompt + LLM 覆盖 + 一组 Tools + 知识（`document_sets`/`attached_documents`/`hierarchy_nodes`）+ `StarterMessage` + 标签 + 可见性（`is_public`/按 user/按 user_group）。`DEFAULT_PERSONA_ID` 为默认体。本质是「可配置助手 + 工具/知识装配」，不是工作流引擎。
2. **执行循环（自研，非 LangGraph）**：`llm_loop.py` 为核心，`run_llm_step` 跑单次 LLM 调用，循环至多 `MAX_LLM_CYCLES` 轮。每轮：LLM 输出 → 解析 tool call（**同时支持原生 function-calling 与 XML 文本式** `extract_tool_calls_from_response_text`）→ `tool_runner.run_tool_calls` 执行 → 回灌 → 命中 `STOPPING_TOOLS_NAMES` 或给出答案为止。引用走 `DynamicCitationProcessor`，输出走 `Emitter`/`Packet` 流式协议，内置长期记忆（`add_memory`）。
3. **Tool / Skill / Agent 三个概念**：
   - **Tool** = chat LLM 可直接调用的函数，注册后挂到 Persona。
   - **Skill** = 打包的能力内容/指令，会话启动时推进 **Craft 沙箱**（`builtin/<skill_id>/`），可由 **ExternalApp 连接**动态生成。
   - **Agent (Persona)** = prompt+tools+knowledge 的装配。
4. **深度研究**为独立模式（`dr_loop.py`）：orchestrator agent →（可选）澄清 → 研究计划 → 派 research-agent 子调用 + think 多轮 → `FINAL_REPORT`。prompts 在 `prompts/deep_research/orchestration_layer.py`。
5. **Craft = Genspark 式超级 Agent**（`build/AGENTS.template.md` 原文：*"You are an AI agent powering Onyx Craft… building and shipping the deliverable, end to end."*）：在临时沙箱 VM（Python3.11 + Node22，Next.js dev server 预启动）里，经 egress 代理注入凭证、审批门控外部动作、用 `opencode` 编码 agent、docker/k8s 管理，端到端造出可运行的网站/PPT/数据/应用。⚠️ `build/api/subscription_check.py` 含云端订阅门控，硬 fork 需替换为自有计费。
6. **MIT/EE 边界**：上述 Agent/研究/Craft/工具/记忆链路**全在 MIT 核心**，可自由商用；EE 仅占企业版 agent 管理 UI（`web/src/app/ee/agents`）与 `backend/ee` 的企业能力。

### A.6 对标 Genspark：差距在「外壳」不在「引擎」
引擎能力（自动编排、深度研究、生成成品）Onyx 已具备；差距集中在 **消费级 UX + 中文/国产模型/微信生态**——而第一块外壳就是**汉化 + UI 资源替换**。

### A.7 路线图（每块各自独立走 spec → plan → 实现）
1. **汉化 + UI 资源替换（本 spec）** ← 现在
2. 剥离 `ee/` + 自有 C 端鉴权（微信/手机号登录）
3. 国产模型默认接入与优选
4. Craft C 端化（去订阅门控 + 垂直生成入口）
5. 微信支付 + 用量计费
6. 国产连接器（飞书/钉钉/语雀）
7. 合规（ICP 备案、内容安全）

---

## Part B — 第一个 spec：汉化 + UI 资源替换（Phase 0「脸面优先」）

### B.1 目标
建立 next-intl i18n 基础设施（中文优先、无路由前缀），完成 **C 端核心路径**文案中文化，并把品牌从 "Onyx" 替换为 **Glomi AI**。后续界面（Craft/研究/projects/admin）走 P1/P2 增量抽取。

### B.2 技术栈现状（已核实）
- Next.js **App Router**，`output: "standalone"`，`typedRoutes: true`，包管理 **bun**。
- **当前无任何 i18n 库**，文案全为 JSX 硬编码英文。
- 无 `[locale]` 路由段。
- `next.config.js` 已用 `withSentryConfig` 包裹，并按 phase 设置 `reactCompiler`。

### B.3 架构决策

**① next-intl「无 i18n 路由」模式（中文优先）**
- 语言用 cookie `NEXT_LOCALE` 切换，默认 `zh`，**URL 不带 `/zh` 前缀**——不引入 `[locale]` 段，不改路由树，不与 `typedRoutes` 冲突。
- 新增文件：
  - `web/src/i18n/request.ts`：`getRequestConfig`，读 cookie，默认 `zh`，加载对应 `messages/*.json`。
  - `web/messages/zh.json`、`web/messages/en.json`：词典（保留 en 以便将来出海/切换）。
- 集成点：
  - `next.config.js`：用 `createNextIntlPlugin('./src/i18n/request.ts')` 包裹现有导出，**需与 `withSentryConfig` 正确组合**（先 nextIntl 再 sentry 或反之，以 build 通过为准）。
  - `web/src/app/layout.tsx`：挂 `NextIntlClientProvider`（传 `messages`），`<html lang>` 按当前 locale。
  - 服务端组件用 `getTranslations()`，客户端组件用 `useTranslations()`。
- 语言切换：提供一个最小 `setLocale` server action / route，写 `NEXT_LOCALE` cookie 后刷新（P0 仅需开关可用，不需精致 UI）。

**② 品牌常量集中化 + 替换纪律**
- 新增 `web/src/lib/brand.ts`：`export const APP_NAME = "Glomi AI"` 等；i18n 加 `brand` namespace。
- ⚠️ **"Onyx" 出现在 157 个 web 文件，绝大多数是代码标识符**（`@onyx-ai/*` import、类型名、注释、第三方 API 名如 connector）。**严禁全局 sed 替换**——只替换「渲染到用户的字符串」。手法：逐处确认 + 先编译后提交。
- C 端硬 fork **绕开 EE 的 `enterpriseSettings.application_name` 白标机制**（EE 授权代码），UI 直接用 `brand.ts` / i18n `brand` namespace。

**③ UI 资源替换清单**

| 资源 | 位置 | P0 处置 |
|---|---|---|
| 站点标题/描述 | `web/src/app/layout.tsx:53`（`metadata.title: "Onyx"`） | 改为 "Glomi AI" + 描述 |
| favicon | `web/public/onyx.ico` + layout 引用 | 占位 favicon（logo 未就绪） |
| 登录页品牌名 | `web/src/app/auth/login/LoginText.tsx:13`（"Onyx" 兜底） | 用 `APP_NAME` |
| 顶部/侧栏 logo 组件 | `web/src/refresh-components/Logo.tsx` | 改为**文字 logo "Glomi AI"** 占位 |
| 主品牌图 | `web/public/logo.png`、`logo-dark.png`、`logotype.png`、`logotype-dark.png` | **占位**（文字或临时图），logo 就绪后一键替换 |
| 初始化加载品牌 | `web/src/components/OnyxInitializingLoader.tsx` | 文案/品牌中文化 |
| Craft 示意图 | `web/public/craft_*.png` | 不动（P1） |

> 注：logo 资源未就绪 → P0 用文字 logo / 占位图，保留替换点；资源就位后单独提交。

### B.4 P0 范围（核心路径，本 spec 实施边界）
- 落地页：`web/src/app/page.tsx`
- 登录：`web/src/app/auth/login/*`
- 主应用壳：`web/src/app/app/*`（`page.tsx`、`components/`、`message/`、`agents/`、`shared/`、`settings` 入口、空状态、开场白、chat 输入框）

### B.5 范围分层（后续 spec，非本 spec）
- **P1**：Craft 界面、深度研究界面、`projects`、设置详情。
- **P2**：admin（C 端弱化，最后译或不译）；`ee/*` 不译（待剥离）。

### B.6 翻译工作流
- namespace 约定：`common / brand / auth / chat / agents / craft / settings`。
- P0（约数十个组件）**人工逐文件**把 JSX 文案换成 `t('key')` 并录入 `zh.json`（人工质量 > 机翻）。
- 提供**硬编码英文扫描脚本**（grep JSX 文本节点）辅助定位漏网文案；不做全自动抽取（易错）。
- 中文做**产品化翻译**（Genspark 式口吻），非直译。

### B.7 Non-goals（YAGNI）
不做 URL 国际化路由；不做浏览器语言自动协商；P0 不碰后端文案 / admin / `ee/`；不动 Craft 内部英文 prompt（那是给模型看的，不是 UI）。

### B.8 风险与缓解
- **next-intl 与 `output: standalone` + `typedRoutes` + `withSentryConfig` 组合** → **必须 `bun run build` 验证**，确认 messages 打进 standalone 产物、Sentry 包裹顺序正确。
- **品牌替换误伤代码标识符** → 只改 UI 字符串，逐处确认，先编译后提交。
- **RSC server/client 边界** → 服务端 `getTranslations`、客户端 `useTranslations` 分清，provider 正确下发 messages。

### B.9 验收标准
- `bun run build` 通过；standalone 启动后**默认中文**。
- C 端核心路径（落地/登录/主应用壳/agents 列表）**无英文残留、无 "Onyx" 品牌残留**（显示 "Glomi AI"）。
- 把 cookie `NEXT_LOCALE` 切为 `en` 能回到英文（证明 i18n 双向可用）。
- 新增文案有清晰 namespace/key 约定，团队可持续抽取。

### B.10 交付物
- next-intl 脚手架（`i18n/request.ts`、`messages/{zh,en}.json`、`next.config.js` 集成、layout provider、locale 切换）。
- `src/lib/brand.ts` + 品牌替换（标题/favicon/logo 占位/登录/加载器）。
- P0 核心路径文案抽取 + 中文词典。
- 硬编码英文扫描脚本。
- `bun run build` 通过的证据。
