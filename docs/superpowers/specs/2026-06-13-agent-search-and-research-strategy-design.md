# 设计文档：中文 Agent 搜索与研究能力层

- **日期**：2026-06-13
- **产品**：Glomi AI
- **关联 Epic**：E3 超级对话调优、E4 深度研究中文化
- **状态**：设计稿，供后续实施计划使用

---

## 1. 问题与目标

Glomi AI 的核心体验不是“有一个搜索工具”，而是用户抛出一个中文问题后，Agent 能判断是否需要搜索、如何拆解问题、该搜哪些来源、何时并行或串行搜索、如何评估证据，并把结果整理成足够可靠的上下文交给 LLM。

当前 Onyx 已有可复用的执行基础：

- 普通对话由 `backend/onyx/chat/llm_loop.py` 驱动，模型在多轮循环中自动选择工具。
- 深度研究由 `backend/onyx/deep_research/dr_loop.py` 驱动，包含研究计划、orchestrator、多 research agent、最终报告。
- `web_search`、`open_url`、`python`、`file_reader`、internal search 等工具已经接入工具系统。

但当前搜索智能主要依赖模型临场读 prompt 和工具描述后自行发挥。Glomi 要补的是一套可复用的中文搜索与证据方法论，让普通对话和深度研究共享同一个“搜索脑子”。

本设计目标：

1. 同时覆盖普通对话的轻量搜索和深度研究的重型搜索。
2. 将“何时搜索、怎么搜、搜哪里、如何评估证据、如何组织上下文”显式化。
3. 优先复用现有 `llm_loop`、`dr_loop`、`web_search`、`open_url`，不重写 Agent runtime。
4. 中文场景优先：中文 query、中文信息源、中文报告结构、中文用户表达习惯。
5. 为未来 E13 超级编排层提供可调用的搜索型能力基础。

---

## 2. 核心判断

E3 默认超级对话调优、E4 深度研究中文化、Agent 搜索策略不是三件孤立的事。它们共享同一个底层问题：

> Agent 如何把用户问题转化为可靠的信息获取计划，并把信息结果组织成可回答、可引用、可追溯的证据上下文。

因此推荐新增一个联合设计主题：

**中文 Agent 搜索与研究能力层**

它不是一个新搜索引擎，也不是新的 superagent runtime，而是夹在“用户问题”和“工具调用/报告生成”之间的方法论与策略层。

---

## 3. 现有架构与差距

### 3.1 普通对话

当前普通对话的真实链路：

1. `process_message.py` 构造 persona、模型和工具。
2. `construct_tools()` 返回当前会话可用工具。
3. `run_llm_loop()` 进入多轮循环。
4. 每轮模型看到 tools，自主决定是否调用 `web_search`、`open_url` 等工具。
5. 工具结果回灌到上下文，下一轮继续回答或继续调用工具。

现有能力足够让模型搜索，但搜索方法论分散在默认 persona prompt、tool guidance、模型自身能力中。普通对话缺少更明确的判断：

- 哪些问题必须搜索。
- 哪些问题不该搜索。
- 原问题是否要拆成多个 query。
- 搜索后是否必须 open URL。
- 证据不足时是否继续搜。
- 最终回答应如何呈现引用、不确定性和冲突。

### 3.2 深度研究

当前深度研究链路：

1. 用户请求带 `deep_research=true`。
2. `process_message.py` 分流到 `run_deep_research_llm_loop()`。
3. clarification step 判断是否需要澄清。
4. research plan step 生成研究计划。
5. orchestrator step 调用 `research_agent`。
6. research agent 调 `web_search` / `open_url` / internal search。
7. final report step 汇总报告并保留引用。

这已经是完整的研究型 agent 架构。中文化不应重写这条链路，而应改：

- planner 如何拆中文问题。
- orchestrator 如何分配中文研究任务。
- research agent 如何生成中文/英文/官方术语 query。
- source routing 如何优先中文可用、可信来源。
- final report 如何写成中文用户愿意读的报告。

### 3.3 当前最大差距

不是工具数量不足，而是缺少一套统一的 **Search Cognition Loop**：

```text
User Query
  -> Search Intent
  -> Question Decomposition
  -> Query Planning
  -> Source Routing
  -> Execution Strategy
  -> Evidence Evaluation
  -> Context Packaging
  -> Answer / Report
```

---

## 4. 产品原则

### 4.1 搜索是 Agent 的认知动作，不是工具按钮

用户不应该理解“我现在要开搜索模式”。普通对话和深度研究都应该在需要时主动搜索，只是深度、预算和输出形态不同。

### 4.2 普通对话也必须有搜索策略

普通对话不是浅问答。只要问题涉及时效、事实精度、政策、价格、产品状态、新闻、引用、对比、争议，Agent 就应该搜索或说明无法可靠回答。

### 4.3 深度研究不是普通搜索放大版

深度研究需要计划、分工、证据矩阵、交叉验证和成稿结构。它可以复用同一套搜索方法论，但运行预算和停止条件不同。

### 4.4 中文不是翻译，而是信息生态切换

中文化不只是把 prompts 翻译成中文，还包括：

- 中文关键词和行业术语。
- 中文官方来源。
- 国内可访问内容源。
- 中文报告结构和表达。
- 必要时中英双语补搜。

### 4.5 先方法论显式化，再做结构化 runtime

第一期先用 prompt/playbook/benchmark 让结果明显变好。只有当 prompt-only 不稳定时，再把 SearchDecision、SearchPlan、EvidencePack 等做成更硬的代码结构。

---

## 5. 目标能力模型

### 5.1 Search Profile

不同场景使用不同 profile，共享同一套策略语言。

| profile | 使用场景 | 预算 | 输出 |
|---|---|---:|---|
| `chat_lite` | 普通对话中的事实/时效/引用问题 | 1-2 轮搜索 | 简洁答案 + 必要引用 |
| `chat_fact_check` | 用户要求核实、对比、找来源 | 1-3 轮搜索 | 结论 + 证据 + 不确定性 |
| `deep_research` | 显式深度研究 | 多轮、多分支 | 中文研究报告 |
| `technical_research` | 技术/API/GitHub/论文问题 | 中等 | 官方文档/代码证据优先 |
| `market_research` | 行业、产品、竞品、商业分析 | 重型 | 来源矩阵 + 结构化分析 |

第一期可先落 `chat_lite` 和 `deep_research`，其他作为 prompt 分类指导。

### 5.2 Search Intent

判断是否需要搜索，以及搜索深度。

必须搜索的信号：

- “最新 / 最近 / 今年 / 今天 / 现在 / 是否已经”
- 价格、政策、法规、版本、CEO、融资、新闻、榜单、产品状态
- 用户要求引用、来源、链接、对比、调研、报告
- 问题具有争议或高事实风险
- 模型知识可能过期

可以不搜索的信号：

- 纯解释型、写作型、头脑风暴型问题
- 用户明确要求不要联网
- 对历史稳定事实的简单询问
- 搜索成本高但收益低，且可以清楚说明假设

### 5.3 Question Decomposition

Agent 不应直接把用户原话扔给搜索引擎。应先拆成信息缺口。

示例：

用户问：“帮我分析 2026 年 AI 编程工具还有没有创业机会。”

应拆成：

- 当前主要玩家和定位。
- 用户群与付费场景。
- 最近模型/IDE/Agent 技术趋势。
- 开源项目和生态变化。
- 价格、分发、留存、差异化难点。
- 仍未被满足的需求。

### 5.4 Query Portfolio

每个搜索任务生成一组 query，而不是一个 query。

Query 组合应覆盖：

- 中文自然说法。
- 英文行业术语。
- 官方名称。
- 同义词和缩写。
- `site:` 或 domain 限定。
- 时间限定。
- 反向关键词，例如“失败、投诉、限制、风险、争议”。

### 5.5 Source Routing

根据问题类型选择来源优先级。

| 问题类型 | 优先来源 |
|---|---|
| 政策/法规 | 政府官网、监管机构、法律法规库、权威媒体解读 |
| 公司/产品 | 官网、公告、财报、招股书、官方博客、发布会 |
| 技术/API | 官方 docs、GitHub、论文、release notes、issue |
| 市场/行业 | 研报、财报、行业媒体、数据平台、头部公司材料 |
| 消费决策 | 评测、社区、价格页、真实用户反馈 |
| 学术/科学 | 论文、机构报告、综述、数据集来源 |

### 5.6 Execution Strategy

并行适用于彼此独立的信息维度，例如市场、政策、竞品、用户反馈。

串行适用于后续搜索依赖前一步发现，例如：

1. 先找到主要玩家。
2. 再逐个打开官网、定价页、财报。
3. 再针对争议点和缺口补搜。

### 5.7 Evidence Evaluation

搜索结果进入 LLM 前要被评价：

- 权威性：官方、一手、二手、社区传闻。
- 时效性：发布时间和是否仍有效。
- 覆盖度：是否回答了原问题的关键维度。
- 重复度：是否只是互相转载。
- 冲突性：不同来源是否矛盾。
- 可引用性：是否有明确 URL、标题、时间、作者/机构。

### 5.8 Evidence Pack

最终给回答模型的上下文应是整理后的证据包，而不是一堆网页原文。

建议格式：

```text
Question:
用户原问题

Search Intent:
为什么搜索，搜索深度是什么

Evidence:
- fact: 关键事实
  source: URL / 标题 / 发布方 / 时间
  confidence: high | medium | low
  relevance: 为什么有用

Conflicts:
- 哪些来源说法不一致

Gaps:
- 哪些关键问题没有找到可靠证据

Answer Guidance:
- 回答应重点覆盖哪些结论
- 哪些地方必须谨慎表达
```

---

## 6. 普通对话设计

### 6.1 目标

普通对话要让用户感觉“这个输入框知道什么时候该查资料”。它不追求报告级深度，但必须避免凭过期知识胡答。

### 6.2 运行方式

普通对话继续走现有 `run_llm_loop()`。第一期不新增单独 controller，而是通过默认 Persona prompt 和 tool guidance 注入搜索策略。

推荐策略：

1. 默认 Persona 明确 Search Intent 规则。
2. web_search guidance 改为中文友好的 query 规划。
3. open_url guidance 明确“搜索后优先打开最可靠页面”。
4. 回答 guidance 要求结论先行、引用简洁、说明不确定性。
5. 普通对话搜索预算默认 1-2 轮；只有用户要求对比/核实时可多一轮。

### 6.3 回答形态

普通对话不应输出长报告。推荐结构：

```text
结论：...

依据：
- ...
- ...

需要注意：...
```

如果证据不足：

```text
我找到了 A 和 B 两类来源，但没有找到能直接证明 X 的权威来源。基于现有资料，更稳妥的判断是...
```

---

## 7. 深度研究设计

### 7.1 目标

深度研究要像中文研究员交付成稿：计划清晰、信息来源可靠、结构完整、引用准确、结论有洞察。

### 7.2 Planner 调整

研究计划 prompt 需要从“列研究步骤”升级为“拆信息缺口”。

计划应包含：

- 用户真正想决策的问题。
- 需要验证的关键假设。
- 主要信息维度。
- 时间范围。
- 来源优先级。
- 可能需要中英双语搜索的点。

### 7.3 Orchestrator 调整

orchestrator 应明确：

- 每个 research_agent 任务必须自包含上下文。
- 每个任务应说明目标来源类型。
- 独立维度可并行，不相关 query 不应混在一起。
- 每轮后要判断：是否已有足够证据、是否有冲突、是否要补搜。

### 7.4 Research Agent 调整

research agent 应遵循：

- 先生成 query portfolio，再执行搜索。
- 中文问题优先中文来源，必要时英文补搜。
- 搜索后必须 open_url 阅读高价值页面，而不是只依赖 snippets。
- 优先一手来源。
- 记录来源质量和证据用途。

### 7.5 Final Report 调整

最终报告推荐结构：

```text
## 摘要

## 关键结论

## 证据与分析

## 分歧与不确定性

## 风险 / 机会 / 建议

## 引用
```

不同任务可微调：

- 市场研究：市场、玩家、需求、商业模式、机会、风险。
- 政策研究：政策原文、适用范围、影响、执行风险。
- 技术研究：方案、实现路径、生态成熟度、坑点。
- 产品对比：维度表、优劣势、适用人群、建议。

---

## 8. 与 E13 的关系

本设计不是 E13 超级编排层。

E13 关心“主控如何自动路由聊天/研究/Craft/代码/多子 agent”。本设计关心“当某个任务需要获取外部信息时，搜索型能力如何判断、计划、执行和组织证据”。

未来 E13 可以把本能力作为一个搜索型子能力：

```text
Super Orchestrator
  -> Search/Research capability
  -> Coding capability
  -> Craft capability
  -> Memory capability
```

如果现在直接做 E13，而搜索能力仍然不稳定，superagent 只会更复杂地放大不稳定性。因此应先把搜索与研究能力层打牢。

---

## 9. 实施分期

### Phase 1：Prompt + Playbook + Benchmark

第一期不改 runtime，只把方法论显式化并验证效果。

- 新增 Agent Search Playbook。
- 调整默认 Persona 中文 prompt。
- 调整普通 chat tool guidance。
- 调整 deep research planner / orchestrator / research agent / final report prompts。
- 建立中文 benchmark 问题集。
- 用真实模型跑对比样例，记录问题和改进。

### Phase 2：结构化策略对象

如果 Phase 1 效果不稳定，再引入结构化对象：

- `SearchIntent`
- `SearchProfile`
- `SearchPlan`
- `SourceRoute`
- `EvidenceItem`
- `EvidencePack`

这些对象可以先服务 deep research，再逐步接入普通 chat。

### Phase 3：来源路由与证据质量增强

后续根据验证结果增强：

- 中文 web search provider 策略。
- 可配置 source routing。
- 证据去重和冲突检测。
- 引用质量评估。
- 搜索成本与用量统计。

---

## 10. 测试与评估

### 10.1 Benchmark 分类

需要建立 20-30 个中文任务，覆盖：

- 最新事实问答。
- 政策/法规研究。
- 产品/公司对比。
- 技术/API 调研。
- 行业机会分析。
- 消费决策。
- 争议事实核验。
- 深度报告。

### 10.2 普通对话验收

- 遇到时效问题会主动搜索。
- 搜索 query 不只是复述用户原话。
- 搜索后会打开高价值页面。
- 回答简洁、中文自然。
- 引用必要且不堆砌。
- 证据不足时会说明不确定性。

### 10.3 深度研究验收

- 研究计划覆盖关键维度。
- research agent 任务不丢上下文。
- 搜索来源有明显优先级。
- 报告中文自然，结论先行。
- 引用准确且能支撑段落。
- 能指出冲突、风险和信息缺口。

### 10.4 回归方式

第一期以人工评审为主，记录每次 benchmark 输出。后续可以把关键样例固化为 eval fixture，对 prompt 改动做回归检查。

---

## 11. 风险与取舍

### 风险 1：Prompt 变长导致普通对话成本上升

第一期应把普通 chat guidance 控制在短规则，不把 deep research 方法论全塞进默认 prompt。

### 风险 2：国产模型对复杂工具策略执行不稳定

需要用真实 Qwen/DeepSeek/Kimi 等模型跑 benchmark。若模型不稳定，再考虑结构化 search planning。

### 风险 3：中文搜索源质量不稳定

搜索质量和搜索策略都重要。第一期先把策略和评估标准写清楚，再验证不同 provider。

### 风险 4：普通对话和深度研究边界变模糊

用 profile 控制预算和输出形态：普通对话快速回答，深度研究成稿报告。

---

## 12. 不做的事

第一期不做：

- 不重写 `llm_loop`。
- 不重写 `dr_loop`。
- 不做 E13 superagent。
- 不做新的搜索引擎。
- 不接复杂 DB 配置后台。
- 不做全自动引用评分系统。
- 不把所有来源路由硬编码成不可调规则。

---

## 13. 验收标准

1. 普通对话能更稳定判断何时需要搜索。
2. 普通对话能生成更好的中文 query，并优先打开可靠来源。
3. 深度研究计划能拆出关键中文信息缺口，而不是泛泛列步骤。
4. research agent 能执行中英双语和来源定向搜索。
5. 最终报告中文结构稳定、引用准确、结论可读。
6. 形成一套可持续迭代的中文 benchmark。
7. 本能力层可作为未来 E13 的搜索型子能力基础。

---

## 14. 后续建议

下一步应先写实施计划，范围限定在 Phase 1：

1. 建立 Agent Search Playbook。
2. 改默认 Persona / tool guidance / deep research prompts。
3. 建中文 benchmark。
4. 用当前默认模型跑 baseline。
5. 根据输出结果再决定是否进入 Phase 2 的结构化策略对象。

这样可以先验证“搜索与研究智能”是否显著提升，再决定是否做更重的 runtime 改造。
