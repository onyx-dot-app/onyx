# Glomi AI 产品蓝图（Product Blueprint v0）

- **日期**：2026-06-12
- **状态**：活文档（讨论稿，会随验证结果迭代）
- **定位**：顶层产品蓝图 + 分期路线。每个 Epic 后续各自走 `spec → plan → 实现`。
- **相关**：能力/Agents 深度解读见 [`2026-06-12-i18n-and-ui-rebrand-design.md`](./2026-06-12-i18n-and-ui-rebrand-design.md) Part A。

---

## 0. 这份文档是什么 / 不是什么

- **是**：Glomi AI 的完整产品蓝图与分期路线,用来指导后续每个 Epic 独立立项。
- **不是**：立即全量实现的承诺。**当前唯一重心 = 验证核心产品能力**;商业化/上线模块（鉴权、支付、合规、部署）写进规划但**延后**,等核心验证可行后再逐步实现。
- **决策原则（本期）**：验证阶段只碰"**核心产品能力**"。鉴权/支付/合规/连接器/部署运维 = 已规划但不在验证期动手。

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

## 2. 目标用户与核心场景（验证假设）

- **用户**：个人知识工作者、学生/研究者、自媒体/内容创作者、独立创业者。
- **验证期要打中的核心场景**：
  1. **深度研究**："帮我研究 X,出一份带引用的报告。"
  2. **超级对话**："边搜边算边写",系统自动调用工具完成多步任务。
  3.（P2）**Craft 创作**："帮我做一个 X 的落地页 / PPT / 数据看板。"
- **要验证的核心问题**：*在中文场景下,这套「自动编排 + 深度研究」能不能给出让用户「惊艳到愿意留下」的结果?* —— 先验证这个,再谈商业化。

---

## 3. 四大产品支柱（用户感知层）

| 支柱 | 底座（Onyx 已有, MIT） | Glomi 要做的 | 期次 |
|---|---|---|---|
| **超级对话** 自动编排工具/研究/生成 | `chat/llm_loop.py`（自研循环 + XML tool-call,兼容国产模型） | 默认体 prompt 调优、轻量搜索策略、中文体验 | 验证期 |
| **深度研究** 带引用研究报告 | `deep_research/dr_loop.py` | 中文搜索策略、证据上下文、中文报告成稿 | 验证期 |
| **Craft 创作交付**（差异化王牌） | `server/features/build/*` 沙箱 | 去订阅门控、沙箱国内化、消费级入口 + 分享页 | 王牌期 P2 |
| **智能体 & 记忆** | `db/persona.py` + `db/memory.py` | 预置中文智能体、个人记忆、分享 | 验证期(轻)/后续 |

---

## 4. 能力取舍地图

详见 i18n spec Part A.4。一句话：**引擎几乎全保留（MIT 可商用,覆盖 ~90% 能力）,你的活在"中国化外壳"**——i18n、国产模型、品牌、（后续）鉴权/支付/合规/部署。

---

## 5. Epics 地图（每个 = 未来独立 spec → plan）

| # | Epic | 期次 | 说明 |
|---|---|---|---|
| **E1** | i18n + 品牌替换 | 🟢 验证期·进行中 | 已有 spec+plan。复用现有 web,中文优先；当前 `brand.png` / `logo.png` 品牌资源已接入默认 wordmark、Logo mark、favicon、公开 logo/logotype 静态资源和默认助手头像 |
| **E2** | 国产模型接入（平台默认 OpenAI-compatible Provider） | 🟢 验证期·进行中 | 第一阶段收敛为平台自动 seed 一个 OpenAI-compatible 主模型到 Onyx 原生 LLMProvider 架构；用户注册后即可用，不进入 Admin LLM 配置页，也不选择模型档位；平台只配置 API base URL、API key、主模型名 |
| **E3** | 超级对话调优 | 🟢 验证期 | 默认 Persona 的中文 system prompt、工具使用策略、回答体验打磨；搜索由 Agent 在 `web_search` 调用中选择 `lite` / `medium` / `deep`，而不是用户手动选择 |
| **E4** | 深度研究中文化 | 🟢 验证期 | 与 E3 共享“中文 Agent 搜索与研究能力层”：问题拆解、query portfolio、来源路由、证据评估、中文报告成稿；默认搜索 provider 第一期接入 Glomi Search Gateway |
| **E5** | Craft C 端化 | 🟡 王牌期 P2 | 去 `subscription_check`、沙箱镜像/网络国内化（k8s）、消费级生成入口 + 模板 |
| **E6** | 生成物分享（Sparkpage 式） | 🟡 王牌期 P2 | 生成结果公开分享页,获客/传播 |
| **E7** | 鉴权重建 | 🔵 商业化期·延后 | 剥离 `ee` 鉴权,微信扫码（网站应用 OAuth）+ 手机号验证码 |
| **E8** | 计费 & 商业化 | 🔵 商业化期·延后 | 微信支付/支付宝,套餐或积分,用量计量（替代 `ee billing`） |
| **E9** | 合规 / 内容安全 | 🔴 上线 gate | ICP 备案、内容安全审核（阿里云/腾讯云 API,输入输出双审）、实名、数据本地化。**有公网用户前必做** |
| **E10** | C 端前台重塑 | 🔵 商业化期 | 在现有 web 上做消费级 UI:首页/发现/历史/分享/品牌视觉 |
| **E11** | 国内云部署运维 | 🔵 上线期 | 阿里云/腾讯云,托管 OpenSearch/PG/Redis/OSS,Craft 的 k8s,监控 |
| **E12** | 国内连接器 | ⚪ 生态·最后 | 飞书/钉钉/语雀/企业微信 |
| **E13** | 超级编排层（Orchestrator / MoA） | 🟡 王牌期 P2（增强） | 把主对话从"单 agent + 工具"升级为"主控**自动路由意图** + **派子 agent**"。基于现成原语：`CodingAgentTool`（子 agent 即工具）、`dr_loop`（orchestrator 模板）、`Emitter/Packet`（子 agent 进度流式展示）。目标：自动判断意图（聊天/研究/建站）、并行派子 agent、汇总（Mixture-of-Agents） |

> **架构洞察（为什么 E13 是"增强"而非"重写"）**：在 Onyx 里「**子 agent = 一个内部跑 agent loop 的工具**」。主对话（`chat/llm_loop.py`）已是"单 agent + 工具自动编排",且 `CodingAgentTool` 就是把内部 agent loop 包成工具的现成范式;深度研究（`dr_loop.py`）已是"orchestrator 规划 → 派 research 子 agent → 汇总"的完整实现,只是靠请求上的 `deep_research` 开关触发（`process_message.py:1223`），不是主控自动决定。**原语齐备（子 agent 即工具 + orchestrator 模板 + 流式协议），E13 差的只是上面那层"自动路由 + 多子 agent 编排"。**

> **E3/E4 联合决策**：超级对话调优和深度研究中文化不应拆成两套搜索逻辑。两者共享一层“中文 Agent 搜索与研究能力”：判断何时搜索、如何拆问题、生成什么 query、搜什么来源、串行还是并行、如何评估证据、如何把证据打包给 LLM。普通对话不再固定等于轻量搜索，Agent 在 `web_search` 工具调用里自行选择 `mode=lite`、`mode=medium` 或 `mode=deep`；完整 Deep Research 仍是独立研究工作流。本期不做关键词规则匹配，也不增加前置 LLM router。默认搜索 provider 接入 Glomi Search Gateway，第一期 Gateway 内部可走 Tavily，后续支持多来源聚合。当前仓库已补一个本地 FastAPI Gateway，便于用 Tavily API key 跑通内测链路；其中 `medium` 模式覆盖一次性研究型检索，`deep` 模式覆盖更高召回检索，两者都使用 bounded query fan-out 和 Tavily raw-content snippet fallback。`open_url` 仍优先真实抓页，但在抓取失败时可把最近 web_search 的 URL snippet 作为明确标注的 fallback evidence 返回；这仍不替代完整 Deep Research 子 agent 编排。Gateway 内部已拆成公共 service + adapter registry + capability policy，后续接 Brave / 国内搜索 / 自研源时新增 adapter，不改 Onyx 工具契约。Search Debug Drawer 作为开发/管理员排障能力，帮助观察 provider、mode、channel、queries、URL、耗时和失败原因，不作为普通用户配置入口。

---

## 6. 分期路线

### Phase A —— 核心能力验证（当前唯一重心）
- **内容**：E1 i18n + E2 国产模型接入（平台默认 OpenAI-compatible 主模型自动初始化）+ E3/E4 中文 Agent 搜索与研究能力层（平台默认 Glomi Search Gateway + Agent 自动选择 Lite/Medium/Deep 搜索 + 深度研究中文报告）。
- **鉴权/支付**：**验证期不做**。用 `AUTH_TYPE=basic` / 单用户 / 内测白名单即可,不碰微信登录、不碰支付。
- **交付物**：一个**中文、接国产模型、对话 + 深度研究可用**的内测版（本地或小范围内测）。
- **验证成功标准**：
  1. 内测用户能用中文完成多类研究/问答/多步任务,且结果**可用、靠谱**;
  2. 深度研究报告**引用准确、可读、成稿质量高**;
  3. 主观信号:用户**愿意再用 / 愿意推荐**（留存与口碑意愿）。
- **退出条件**：验证通过 → 进 Phase B;不通过 → 调整产品方向（而不是继续投商业化）。

### Phase B —— 亮王牌（Craft + 超级编排）
- **内容**：E5 Craft C 端化 + E6 生成物分享 + **E13 超级编排层**。沙箱国内化（镜像/网络/k8s）。
- **交付物**：能**生成并分享**站点 / PPT / 数据 / 海报,且主控能**自动路由 + 调度子 agent**（聊天/研究/建站无感切换）——对标 Genspark 的核心差异化。
- **次序提示**：先 E5/E6 把 Craft 变成"可派的子 agent",再上 E13 让主控自动编排;验证期（Phase A）用现有"对话 + 深度研究开关"已足够像 Genspark,不必提前做 E13。

### Phase C —— 商业化与上线（验证可行后再启动）
- **内容**：E7 鉴权（微信/手机）→ E8 计费 → **E9 合规（内容安全先行）** → E10 前台重塑 → E11 国内云部署 → E12 连接器。
- ⚠️ **硬约束**：E9 的"内容安全审核"是**公网开放给真实用户前的法规 gate**,必须先于公测,不能真等到最后。

---

## 7. 待决策点（open,验证可行后再定）

| 决策 | 现状 | 倾向/建议 |
|---|---|---|
| **对话模型** | ✅ 已定 | 验证期优先平台统一配置一个 OpenAI-compatible 主模型；C 端不暴露 API key/base URL/参数配置，也不提供模型档位。规模化/合规后再考虑多模型策略或自部署开源模型 |
| **默认搜索服务** | ✅ 已定 | Onyx 侧自动 seed `Glomi Search / glomi` provider，配置只暴露 Gateway base URL、API key、可选 channel；仓库内提供本地 `onyx.search_gateway.server`，第一期把 `channel=tavily` 转成 Tavily 搜索；Agent 在 `web_search` 工具调用中选择 `lite` / `medium` / `deep`，不做代码规则匹配，不增加前置 LLM router；Gateway 的 `medium` / `deep` 会做限量 query fan-out、Tavily advanced search、raw-content snippet fallback；`open_url` 抓取失败时可使用最近 web_search snippet 作为标注过的 fallback evidence；Gateway 内部用 adapter capability matrix 支持未来 Tavily / Brave / 国内搜索 / 自研源切换 |
| **embedding 检索模型** | forward note | 仅当做「文档/知识库 RAG」时才需换中文 embedding（BGE / Qwen-embedding / 云端中文）。纯深度研究（走 web 搜索）验证期不依赖,先不管 |
| **商业模式** | 未定 | 订阅 / 积分按量 / 免费+增值,Phase C 前定 |
| **定价与套餐** | 未定 | 随商业模式定 |
| **是否做团队版** | 暂不（当前 C 端优先） | 若 B 端获客需求出现再议 |
| **私有化交付选项** | 未定 | 视目标客户 |

---

## 8. 与现有文档/代码的关系

- 本蓝图 = **顶层**;每个 Epic 各自走独立的 `spec → plan → 实现`。
- 已落地：**E1**（i18n + UI 资源替换）的 spec 与 plan。
- **下一步建议**：E1 已落，E2 纠偏为“注册即有平台默认 OpenAI-compatible 主模型”，以 `docs/superpowers/specs/2026-06-14-platform-default-openai-compatible-llm-design.md` 为实施依据；E3/E4 继续以 `docs/superpowers/specs/2026-06-13-agent-search-and-research-strategy-design.md` 为搜索方法论基础，平台默认 Glomi Search Gateway 与 Agent 自动 Lite/Medium/Deep 搜索模式已按 `docs/superpowers/specs/2026-06-15-platform-default-glomi-search-gateway-design.md` 进入一期实现，本地 Gateway 与 open_url snippet fallback 已可用，后续重点是解决本地 Tavily TLS 连通性后做端到端中文搜索/研究 benchmark。

---

## 9. 风险

- **验证期最大风险**：核心能力在中文场景"不够惊艳" → 所以**先验证再投商业化**是正确次序。
- **自维护成本**：硬 fork 脱离上游,引擎进化/安全补丁全自管。
- **内容合规**：公网开放前必须有内容安全审核（E9 不可省）。
- **Craft 国内化复杂度**：沙箱镜像/网络/k8s 国内化是 Phase B 的主要工程风险。
- **模型成本**：深度研究/Craft 多轮调用 token 消耗大,需成本监控（影响商业模式）。
