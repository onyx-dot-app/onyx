# Glomi AI 产品蓝图（Product Blueprint v0）

- **日期**：2026-06-12
- **状态**：活文档（Phase A 已完成核心验证，当前进入 Phase B / Glomi Forge 王牌能力启动）
- **定位**：顶层产品蓝图 + 分期路线。每个 Epic 后续各自走 `spec → plan → 实现`。
- **相关**：能力/Agents 深度解读见 [`2026-06-12-i18n-and-ui-rebrand-design.md`](./2026-06-12-i18n-and-ui-rebrand-design.md) Part A。

---

## 0. 这份文档是什么 / 不是什么

- **是**：Glomi AI 的完整产品蓝图与分期路线,用来指导后续每个 Epic 独立立项。
- **不是**：立即全量商业化 SaaS 的承诺。**Phase A 核心能力验证已通过**，当前重心切到 Phase B：以 **Glomi Forge** 为自研生成交付运行时，逐步替代 Onyx Craft 独立工作台的产品心智。
- **决策原则（本期）**：Phase B 优先让用户从中文需求拿到可预览、可迭代、可分享的成品。鉴权/支付/合规/连接器/正式部署运维仍按 Phase C 节奏推进；公网开放前必须补内容安全与合规 gate。

---

## 1. 定位与北极星

- **产品**：C 端消费级超级 Agent（中文版 Genspark）。**Web/PC 优先**。
- **北极星**：*"一个中文输入框,自动帮你把活干完并交付成品。"* 用户不配置工具、不懂提示词,说需求 → 拿结果。
- **关键约束（已决策）**：
  - **硬 fork**：后端自管,不吃上游 Onyx 更新。⚠️ 永不点 GitHub "Sync fork"。
  - **复用 Onyx MIT 核心引擎**（对话 loop / 深度研究 / Craft 沙箱 / 工具 / Persona / 记忆）。
  - **Web 优先 → 最大化复用现有 Next.js 前端**,前台做"消费级重塑"而非重写。
  - `ee/`（企业授权代码：SSO/billing/analytics/whitelabel）**剥离重建**,延后。

---

## 2. 目标用户与核心场景

- **用户**：个人知识工作者、学生/研究者、自媒体/内容创作者、独立创业者。
- **Phase A 已验证的核心场景**：
  1. **深度研究**："帮我研究 X,出一份带引用的报告。"
  2. **超级对话**："边搜边算边写",系统自动调用工具完成多步任务。
- **Phase B 要打中的交付场景**：
  1. **Glomi Forge 创作**："帮我做一个 X 的落地页 / PPT / 数据看板 / 小工具。"
  2. **生成物分享**："把结果变成一个能发给别人看的页面。"
  3. **主控派发**：用户仍从一个中文输入框开始，系统自动判断该聊天、研究还是进入 Glomi Forge 生成交付。
- **当前要验证的问题**：*在中文场景下，GlomiAI 能不能不只回答问题，而是稳定交付可运行、可修改、可传播的成品?*

---

## 3. 四大产品支柱（用户感知层）

| 支柱 | 底座（Onyx 已有, MIT） | Glomi 要做的 | 期次 |
|---|---|---|---|
| **超级对话** 自动编排工具/研究/生成 | `chat/llm_loop.py`（自研循环 + XML tool-call,兼容国产模型） | 已完成 Phase A 验证；Phase B 作为主控入口派发 Glomi Forge / Deep Research | 已验证，继续增强 |
| **深度研究** 带引用研究报告 | `deep_research/dr_loop.py` | 已完成中文搜索策略、证据上下文、中文报告成稿的一期验证 | 已验证，继续增强 |
| **Glomi Forge 创作交付**（差异化王牌） | 规划中 `backend/onyx/glomi_forge/*`；现有 `server/features/build/*` 作为 Onyx Craft 参考实现 | 自研 Daytona + Pi 生成交付运行时：消费级入口、模板、资源治理、分享页、主控派发 | Phase B 当前重心 |
| **智能体 & 记忆** | `db/persona.py` + `db/memory.py` | 预置中文智能体、个人记忆、分享 | Phase B/后续增强 |

---

## 4. 能力取舍地图

详见 i18n spec Part A.4。一句话：**引擎几乎全保留（MIT 可商用,覆盖 ~90% 能力）,你的活在"中国化外壳"**——i18n、国产模型、品牌、（后续）鉴权/支付/合规/部署。

---

## 5. Epics 地图（每个 = 未来独立 spec → plan）

| # | Epic | 期次 | 说明 |
|---|---|---|---|
| **E1** | i18n + 品牌替换 | ✅ Phase A 已验证 | 已有 spec+plan。复用现有 web,中文优先；当前 `brand.png` / `logo.png` 品牌资源已接入默认 wordmark、Logo mark、favicon、公开 logo/logotype 静态资源和默认助手头像 |
| **E2** | 平台模型目录与模型选择 | ✅ Phase A 已验证，Phase B 继续服务 Glomi Forge | 从“每账户一个默认模型”升级为后端控制的供应商分组 Glomi Model Catalog：供应商下挂 provider 配置与模型 ID 数组，当前测试支持 GPT（既有平台 OpenAI-compatible gateway）和 MiniMax（官方 `https://api.minimax.io/v1` OpenAI-compatible endpoint，按多模态模型暴露图片输入）；后端返回供应商分组、模型能力（视觉、推理、角色标签）给前端选择器，并在读取 `/api/chat/available-models` 时按 catalog / `GLOMI_ENABLED_LLM_MODELS` 强制过滤；当 Glomi catalog 开启时，C 端只返回 catalog provider，避免旧通用 `OpenAI-Compatible` provider 或上游 `/models` 全量结果泄漏到模型下拉；OpenAI-compatible transport 只作为调用通道，供应商差异由后端 response normalization 兜底，stream 和 invoke 路径都会把供应商 tagged reasoning 归一化到 reasoning 字段；Glomi Forge 需要复用同一模型目录并做 Pi/沙箱侧 provider 映射 |
| **E3** | 超级对话调优 | ✅ Phase A 已验证，Phase B 转为主控入口 | 默认 Persona 的中文 system prompt、工具使用策略、回答体验打磨；搜索由 Agent 在 `web_search` 调用中选择 `lite` / `medium` / `deep`；普通 chat 研究型回答采用自适应但克制的表达策略；Phase B 要把“生成交付意图”路由到 Glomi Forge |
| **E4** | 深度研究中文化 | ✅ Phase A 已验证，继续增强 | 与 E3 共享“中文 Agent 搜索与研究能力层”：问题拆解、query portfolio、来源路由、证据评估、中文报告成稿；默认搜索 provider 第一期接入 Glomi Search Gateway |
| **E5** | Glomi Forge 地基与 C 端化 | 🚀 Phase B 当前重心 | 自研 `glomi_forge` 运行时：Daytona sandbox substrate + Pi builder harness + ForgeSession/ForgeSpec/ForgeEvent；支持平台模型目录里的 OpenAI-compatible 模型、资源限额与回收、消费级生成入口 + 模板 |
| **E6** | 生成物分享（Sparkpage 式） | 🚀 Phase B 当前重心 | 生成结果公开分享页,获客/传播；分享页要成为 Glomi Forge 成品的默认出口，而不是隐藏在工作台里 |
| **E7** | 鉴权重建 | 🔵 商业化期·延后 | 剥离 `ee` 鉴权,微信扫码（网站应用 OAuth）+ 手机号验证码 |
| **E8** | 计费 & 商业化 | 🔵 商业化期·延后 | 微信支付/支付宝,套餐或积分,用量计量（替代 `ee billing`） |
| **E9** | 合规 / 内容安全 | 🔴 上线 gate | ICP 备案、内容安全审核（阿里云/腾讯云 API,输入输出双审）、实名、数据本地化。**有公网用户前必做** |
| **E10** | C 端前台重塑 | 🔵 商业化期 | 在现有 web 上做消费级 UI:首页/发现/历史/分享/品牌视觉 |
| **E11** | 国内云部署运维 | 🔵 上线期 | 阿里云/腾讯云,托管 OpenSearch/PG/Redis/OSS,Glomi Forge 的 Daytona/k8s 底座,监控 |
| **E12** | 国内连接器 | ⚪ 生态·最后 | 飞书/钉钉/语雀/企业微信 |
| **E13** | 超级编排层（Orchestrator / MoA） | 🚀 Phase B 当前重心（在 Glomi Forge 可稳定产物后接入） | 把主对话从"单 agent + 工具"升级为"主控**自动路由意图** + **派子 agent**"。基于现成原语：`CodingAgentTool`（子 agent 即工具）、`dr_loop`（orchestrator 模板）、`Emitter/Packet`（子 agent 进度流式展示）。目标：自动判断意图（聊天/研究/建站/做 PPT/做看板/做页面）、并行派子 agent、汇总（Mixture-of-Agents） |

> **架构洞察（为什么 E13 是"增强"而非"重写"）**：在 Onyx 里「**子 agent = 一个内部跑 agent loop 的工具**」。主对话（`chat/llm_loop.py`）已是"单 agent + 工具自动编排",且 `CodingAgentTool` 就是把内部 agent loop 包成工具的现成范式;深度研究（`dr_loop.py`）已是"orchestrator 规划 → 派 research 子 agent → 汇总"的完整实现,只是靠请求上的 `deep_research` 开关触发（`process_message.py:1223`），不是主控自动决定。**原语齐备（子 agent 即工具 + orchestrator 模板 + 流式协议），E13 差的只是上面那层"自动路由 + 多子 agent 编排"。**

> **E3/E4 联合决策**：超级对话调优和深度研究中文化不应拆成两套搜索逻辑。两者共享一层“中文 Agent 搜索与研究能力”：判断何时搜索、如何拆问题、生成什么 query、搜什么来源、串行还是并行、如何评估证据、如何把证据打包给 LLM。普通对话不再固定等于轻量搜索，Agent 在 `web_search` 工具调用里自行选择 `mode=lite`、`mode=medium` 或 `mode=deep`；但搜索强度只控制证据收集，不控制最终回答长度。普通 chat 的研究型回答默认应让用户更快抓住判断、证据强弱和下一步，而不是把每个调研问题都写成完整报告；Agent 可以自适应选择表达形态，但不使用固定模板。完整 Deep Research 仍是独立研究工作流。本期不做关键词规则匹配，也不增加前置 LLM router。默认搜索 provider 接入 Glomi Search Gateway，第一期 Gateway 内部可走 Tavily，后续支持多来源聚合。当前仓库已补一个本地 FastAPI Gateway，便于用 Tavily API key 跑通内测链路；其中 `medium` 模式覆盖一次性研究型检索，`deep` 模式覆盖更高召回检索，两者都使用 bounded query fan-out 和 Tavily raw-content snippet fallback。`open_url` 仍优先真实抓页，但在抓取失败时可把最近 web_search 的 URL snippet 作为明确标注的 fallback evidence 返回；这仍不替代完整 Deep Research 子 agent 编排。Gateway 内部已拆成公共 service + adapter registry + capability policy，后续接 Brave / 国内搜索 / 自研源时新增 adapter，不改 Onyx 工具契约。Search Debug Drawer 作为开发/管理员排障能力，帮助观察 provider、mode、channel、queries、URL、耗时和失败原因，不作为普通用户配置入口。

---

## 6. 分期路线

### Phase A —— 核心能力验证（已完成）
- **内容**：E1 i18n + E2 平台模型目录与模型选择（后端按供应商同步 GPT / MiniMax provider 与模型能力画像到 tenant）+ E3/E4 中文 Agent 搜索与研究能力层（平台默认 Glomi Search Gateway + Agent 自动选择 Lite/Medium/Deep 搜索 + 深度研究中文报告）+ 聊天运行态刷新恢复 + 基于后端模型能力的图片粘贴/上传入口。
- **结论**：核心中文对话、搜索、深度研究和平台默认模型能力已经完成验证，允许产品路线进入 Phase B。
- **鉴权/支付**：Phase A 未做，仍不作为 Phase B 起步阻塞项。继续用 `AUTH_TYPE=basic` / 单用户 / 内测白名单即可；公网开放前再进入 Phase C 补齐。
- **交付物**：一个**中文、接国产模型、对话 + 深度研究可用**的内测版（本地或小范围内测）。
- **已满足的验证标准**：
  1. 内测用户能用中文完成多类研究/问答/多步任务,且结果**可用、靠谱**;
  2. 深度研究报告**引用准确、可读、成稿质量高**;
  3. 主观信号:用户**愿意再用 / 愿意推荐**（留存与口碑意愿）。
- **退出状态**：验证通过 → 已进入 Phase B。

### Phase B —— 亮王牌（Glomi Forge + 生成物分享 + 主控派发，当前重心）
- **内容**：E5 Glomi Forge 地基与 C 端化 + E6 生成物分享 + **E13 超级编排层**。新运行时采用 Daytona + Pi strangler 路线，与现有 Onyx Craft/opencode 工作台并行，feature flag 控制；Glomi Forge 复用 Phase A 平台模型目录，OpenAI-compatible 模型在 GlomiAI 内保留独立 provider 类型，在 Pi/沙箱边界映射到可用 provider。
- **核心定位**：Glomi Forge 不是侧边栏里的独立 Build 工作台，而是 GlomiAI 的“生成交付运行时”。用户仍从中文输入框开始；当需求需要页面、PPT、报告、看板、小工具或可分享成品时，主控应把任务派给 Glomi Forge。
- **交付物**：能**生成并分享**站点 / PPT / 数据看板 / 海报 / 报告 / 小工具,且主控能**自动路由 + 调度子 agent**（聊天/研究/建站/做 PPT 无感切换）——对标 Genspark 的核心差异化。
- **次序提示**：先 E5 把 Glomi Forge A 节点跑通（`glomi_forge` 地基 + 落地页端到端），再 E6 做分享闭环，最后 E13 把 Glomi Forge 包成主控可派发的生成子 agent。不要一上来重写整个主控；Onyx Craft 只作为参考/兜底路径，不再承载新能力命名。

#### Phase B Glomi Forge 集成/改造路线

| 阶段 | 目标 | 要改造的重点 |
|---|---|---|
| **B0 命名与地基收敛** | Glomi Forge 与 Onyx Craft 概念切开 | 产品名 `Glomi Forge`；包名 `glomi_forge`；API `/api/glomi-forge`；feature flag `ENABLE_GLOMI_FORGE`；DB 表 `glomi_forge_session/event` |
| **B1 A 节点端到端** | 用户可以直接用 Glomi Forge 生成成品 | Daytona sandbox + Pi builder + landing page template；`ForgeSpec` / `ForgeSession` / `ForgeEvent`；最小内测页与预览 |
| **B2 运行稳定与资源治理** | 让 Glomi Forge 在当前 Linux/国内 k8s 环境可控运行 | Daytona 自托管、snapshot、资源限额、空闲回收、任务超时、失败恢复、可观测日志 |
| **B3 生成物分享闭环** | 让 Glomi Forge 产物天然能传播 | 把 web artifact、报告、PPT 等输出统一成可公开/私密分享链接；分享页不暴露工作台复杂 UI；支持继续编辑/复制任务 |
| **B4 主对话派发 Glomi Forge** | 一个输入框自动进入生成模式 | 在主 chat 中识别“要交付成品”的意图，创建/复用 ForgeSession，流式展示进度，把预览和最终产物回填到对话；Deep Research 继续负责研究，Glomi Forge 负责可运行/可展示交付物 |

#### Glomi Forge 最大化发挥的原则

- **保留强项**：sandbox 隔离、实时预览、文件系统、快照/恢复、skills/模板、approvals 是生成交付运行时的核心资产；Glomi Forge 重新实现这些能力，不沿用 Onyx Craft 的用户心智。
- **改造入口**：Onyx 原始 Craft 偏企业知识库工作台；Glomi Forge 要把入口改成中文消费级生成任务，而不是让用户理解 session、apps、skills、scheduled tasks。
- **控制资源**：单机 Linux 不适合无限预创建 sandbox。Phase B 起步必须把并发、闲置回收、容器内存/CPU、任务超时和失败清理作为产品能力的一部分。
- **主控解耦**：短问答和研究仍走 chat / Deep Research；需要产物交付才进入 Glomi Forge。这样既最大化 Forge 价值，也避免所有请求都进重型 sandbox。
- **分享优先**：Glomi Forge 的商业与传播价值不在“生成过程很酷”，而在“成品能被打开、检查、转发、二次编辑”。

### Phase C —— 商业化与上线（验证可行后再启动）
- **内容**：E7 鉴权（微信/手机）→ E8 计费 → **E9 合规（内容安全先行）** → E10 前台重塑 → E11 国内云部署 → E12 连接器。
- ⚠️ **硬约束**：E9 的"内容安全审核"是**公网开放给真实用户前的法规 gate**,必须先于公测,不能真等到最后。

---

## 7. 待决策点（open,验证可行后再定）

| 决策 | 现状 | 倾向/建议 |
|---|---|---|
| **对话模型** | ✅ 已定 | Phase A 已从单主模型升级为平台内置模型目录；当前进一步收敛为“供应商 → provider 配置 → 模型 ID 数组”的后端控制结构。第一期测试只开放 GPT（既有平台 gateway，默认 `gpt-5.5`）和 MiniMax（官方 OpenAI-compatible endpoint，默认 `MiniMax-M3`，按多模态模型开放图片输入），后端同步到每个 tenant 的 LLMProvider/ModelConfiguration，并返回 `supplier_id`、`supplier_display_name`、`supports_image_input`、推理能力和角色标签给前端模型选择器。C 端不暴露 API key/base URL/provider 配置，只选择平台开放的模型；实际向用户暴露哪些 catalog 模型 ID 由启动环境变量 `GLOMI_ENABLED_LLM_MODELS` 控制（逗号分隔，匹配 GPT / MiniMax / 后续扩展 supplier 的模型 ID，大小写不敏感；默认仅 `gpt-5.5`，要同时开放 MiniMax 可设为 `gpt-5.5,MiniMax-M3`）。`/api/chat/available-models` 会在读取时再次应用这套 allowlist；当 Glomi catalog 开启时，旧的通用 `OpenAI-Compatible` provider 也不会进入普通用户模型下拉，因此 DB 中历史保留或 `/models` fetch 写入的额外可见模型不会以独立分组泄漏；MiniMax 等 OpenAI-compatible 供应商若返回 `<think>` 标签，后端 stream 路径会归一化为 reasoning packet 而不是正文，`invoke()` 汇总响应也会归一化到 reasoning 字段；Phase B 继续让 Glomi Forge 复用这套目录 |
| **默认搜索服务** | ✅ 已定 | Onyx 侧自动 seed `Glomi Search / glomi` provider，配置只暴露 Gateway base URL、API key、可选 channel；仓库内提供本地 `onyx.search_gateway.server`，第一期把 `channel=tavily` 转成 Tavily 搜索；Agent 在 `web_search` 工具调用中选择 `lite` / `medium` / `deep`，不做代码规则匹配，不增加前置 LLM router；Gateway 的 `medium` / `deep` 会做限量 query fan-out、Tavily advanced search、raw-content snippet fallback；`open_url` 抓取失败时可使用最近 web_search snippet 作为标注过的 fallback evidence；Gateway 内部用 adapter capability matrix 支持未来 Tavily / Brave / 国内搜索 / 自研源切换 |
| **Glomi Forge 集成路线** | ✅ 已定 | Phase B 已启动。先跑通 `glomi_forge` A 节点与资源治理，再做消费级模板入口与生成物分享，最后把 Glomi Forge 包成主控可派发的生成子 agent。短问答/研究不进 sandbox，需要可预览、可迭代、可分享成品时才派发 Glomi Forge |
| **embedding 检索模型** | forward note | 仅当做「文档/知识库 RAG」时才需换中文 embedding（BGE / Qwen-embedding / 云端中文）。纯深度研究（走 web 搜索）暂不依赖，Phase B 起步先不作为 Glomi Forge 阻塞项 |
| **商业模式** | 未定 | 订阅 / 积分按量 / 免费+增值,Phase C 前定 |
| **定价与套餐** | 未定 | 随商业模式定 |
| **是否做团队版** | 暂不（当前 C 端优先） | 若 B 端获客需求出现再议 |
| **私有化交付选项** | 未定 | 视目标客户 |

---

## 8. 与现有文档/代码的关系

- 本蓝图 = **顶层**;每个 Epic 各自走独立的 `spec → plan → 实现`。
- 已落地：**E1**（i18n + UI 资源替换）的 spec 与 plan。
- **下一步建议**：Phase A 已完成核心验证。Phase B 应优先推进 Glomi Forge：先做 `glomi_forge` A 节点（Daytona + Pi + 落地页端到端）和资源治理，再做 C 端模板入口和分享页，最后接入主对话派发。E3/E4 的中文搜索与研究能力继续作为 Glomi Forge 的上游材料来源，不替代 Forge 的生成交付职责。

---

## 9. 风险

- **Phase B 最大风险**：Glomi Forge 能力强但系统重，若没有资源治理和清晰派发边界，会拖垮单机部署并让普通问答也变慢。
- **自维护成本**：硬 fork 脱离上游,引擎进化/安全补丁全自管。
- **内容合规**：公网开放前必须有内容安全审核（E9 不可省）。
- **Glomi Forge 国内化复杂度**：Daytona 自托管、sandbox 镜像/网络/国内 k8s 是 Phase B 的主要工程风险。
- **Glomi Forge 模型兼容风险**：平台模型目录里的 GPT-5.5、Qwen3.7 Plus、GLM-5.2 等可通过 OpenAI-compatible 进入 Pi/沙箱 builder，但不同厂商对 tool calling、streaming、reasoning 参数和长上下文的兼容性不完全一致，需要后续用真实 Forge 任务做模型白名单与降级策略。
- **模型成本**：深度研究/Glomi Forge 多轮调用 token 消耗大,需成本监控（影响商业模式）。
