# GlomiAI

GlomiAI 是基于 Onyx MIT 核心能力继续演进的中文消费级超级 Agent。Phase A 已完成中文对话、搜索、深度研究和平台模型能力的核心验证；当前进入 Phase B，重点是把 Craft 改造成 GlomiAI 的生成交付运行时。

> 一个中文输入框，自动帮用户把活干完并交付成品。

这个仓库是 GlomiAI 的产品和工程主干。它复用 Onyx 已有的对话循环、深度研究、工具系统、RAG、Craft 沙箱、Persona 和记忆等基础能力，并在中文场景、国产模型、平台默认搜索、消费级体验和后续生成物交付上继续改造。

## 当前定位

- **产品方向**：C 端消费级超级 Agent，Web / PC 优先。
- **当前阶段**：Phase B Craft 王牌能力启动。
- **北极星体验**：用户不配置工具、不懂提示词，只输入中文需求，系统自动搜索、研究、分析、写作和交付。
- **工程策略**：硬 fork，自管后端，不依赖上游 Onyx 同步。
- **底座选择**：最大化复用 Onyx 的成熟 Agent runtime、Deep Research、Craft sandbox 和 Next.js 前端；Phase B 先把 Craft 跑稳、C 端化、接分享闭环，再接入主控派发。

## 当前分支状态

这张表回答“现在已经做了哪些”。状态以当前分支代码、`summary.md` 和 `docs/GlomiAI.md` 为准。

| 模块 | 状态 | 已完成内容 | 下一步 |
|---|---|---|---|
| E1 i18n + 品牌替换 | Phase A 已验证 | 中文优先与 UI rebrand 的设计/计划已沉淀，复用现有 Web 前端做消费级重塑 | Phase B 继续服务 Craft 入口、分享页和生成物展示 |
| E2 平台模型目录 | Phase A 已验证，继续服务 Craft | 从单默认 LLM 演进为平台模型目录；后端同步模型能力画像，前端只暴露平台可选模型，不暴露 API key/base URL | Craft 侧复用同一模型目录，并处理 OpenAI-compatible 到 OpenCode 沙箱 provider 的映射 |
| E3 中文超级对话 | Phase A 已验证，转为主控入口 | 普通 chat tool guidance 引入中文搜索策略；`web_search` 支持 `lite / medium / deep`；Agent 在工具调用中自行选择搜索强度 | 增加“生成交付意图”识别，把页面/PPT/看板/小工具任务派发给 Craft |
| E4 中文深度研究 | Phase A 已验证，继续增强 | Deep Research research agent 默认 `mode=deep`；planner/orchestrator/research-agent/report prompt 已加入中文研究方法论 | 作为 Craft 的上游材料来源，为页面、报告、看板等生成物提供证据和结构 |
| Glomi Search Gateway | 已实现本地一期 | Onyx 侧只接 `glomi` provider；本地 FastAPI Gateway 支持 Tavily channel、`lite / medium / deep`、query fan-out、raw-content snippet fallback | 接 Brave / 国内搜索 / 自研源；做渠道 fallback、成本限制和线上部署形态 |
| Gateway adapter 架构 | 已实现 | Gateway 内部拆出 adapter protocol、capability matrix、common service、URL dedupe 和 channel routing | 新增具体 adapter 时不改 Onyx `web_search` 契约 |
| Search Debug Drawer | 已实现 | 后端流式发送 `search_tool_debug_delta`；前端在 Web Search FULL timeline 中折叠展示 provider、mode、queries、URLs、耗时和错误 | 后续按需要接入更完整的开发/管理员排障页 |
| Craft C 端化 | Phase B 当前重心 | 已明确要把 Craft 从独立 Build 工作台改造成 GlomiAI 的生成交付运行时 | 先做稳定运行/资源治理/模型适配，再做消费级模板入口、分享页和主控派发 |
| 超级编排层 E13 | Phase B 当前重心，依赖 Craft 稳定产物 | 复用 `CodingAgentTool` 与 `dr_loop` 原语，主对话仍是一号入口 | 在 Craft 可稳定生成后做自动路由、多子 agent、MoA 汇总 |
| 鉴权/支付/合规/部署 | 延后 | 已进入产品蓝图，但不阻塞 Phase B 起步 | Phase C 处理商业化与上线；公网前必须先做内容安全 |

## 已完成功能的逻辑说明

### 1. 平台模型目录

目标：用户注册后默认能用平台模型，不进入 Admin，不看到 API key/base URL；Phase B 中 Craft 也复用同一套模型目录。

运行链路：

```text
平台 env
  -> setup_postgres() / tenant provisioning
  -> seed/sync Glomi model catalog
  -> LLMProvider / ModelConfiguration
  -> model capability metadata
  -> Onyx default CHAT flow
  -> chat / deep research / title / Craft provider mapping
```

关键文件：

- `backend/onyx/db/consumer_llm.py`
- `backend/onyx/setup.py`
- `backend/ee/onyx/server/tenants/provisioning.py`
- `backend/onyx/configs/app_configs.py`

当前行为：

- C 端用户不配置 provider、API key、base URL。
- 后端负责同步平台开放模型与能力画像。
- 用户只选择平台开放的模型，不接触底层 provider 配置。
- Craft 沙箱侧需要把 OpenAI-compatible 模型映射到 OpenCode 可用 provider，同时保留 GlomiAI 后端内部 provider 边界。

### 2. 中文 Agent 搜索与研究能力层

目标：不是“接一个搜索 API”，而是让 Agent 知道什么时候搜、怎么搜、搜哪里、如何评估证据。

共享方法论：

```text
User Query
  -> Search Intent
  -> Question Decomposition
  -> Query Portfolio
  -> Source Routing
  -> web_search / open_url
  -> Evidence Evaluation
  -> Answer / Report
```

普通对话和深度研究共享这套搜索脑子，但预算和输出不同：

- 普通 chat：快速判断是否需要搜索，输出简洁答案、依据和不确定性。
- Deep Research：先规划信息缺口，再派 research agent 搜索和阅读页面，最后生成中文研究报告。

关键文件：

- `backend/onyx/prompts/search_strategy.py`
- `backend/onyx/prompts/tool_prompts.py`
- `backend/onyx/prompts/deep_research/*`
- `backend/onyx/evals/glomi_search_research_benchmark.py`

当前边界：

- 不重写 `llm_loop`。
- 不重写 `dr_loop`。
- 不增加前置 SearchModeRouter LLM 调用。
- 不做后端关键词规则匹配。
- 搜索强度由 Agent 在 `web_search` 工具参数里选择。

### 3. Glomi Search Gateway 和 `web_search` 模式

目标：Onyx 侧只接 Glomi 自己的 Gateway，不直接绑定 Tavily 官方协议。

Onyx 侧链路：

```text
Agent calls web_search({ queries, mode })
  -> WebSearchTool 清洗 queries / mode
  -> active InternetSearchProvider = Glomi Search / glomi
  -> GlomiSearchClient.search_batch()
  -> POST {Gateway}/search
  -> SearchDocsResponse / citations / timeline
```

Gateway 侧链路：

```text
POST /search
  -> Bearer token auth
  -> SearchGatewayService
  -> channel registry
  -> mode policy: lite / medium / deep
  -> query fan-out when medium/deep
  -> adapter capabilities degrade if needed
  -> upstream adapter, first channel = tavily
  -> URL dedupe / result cap
  -> normalized Gateway response
```

搜索模式：

| mode | 使用场景 | Gateway 行为 |
|---|---|---|
| `lite` | 简单事实补全、低延迟问答 | 不扩 query；Tavily basic；不取 raw content |
| `medium` | 框架/项目/产品/公司等一次性研究型检索 | 最多 5 条 query fan-out；Tavily advanced；raw-content snippet 截断到 800 字符 |
| `deep` | 高召回搜索、事实核查、Deep Research research agent | 最多 8 条 query fan-out；Tavily advanced；raw-content snippet 截断到 1200 字符 |

关键文件：

- `backend/onyx/db/glomi_search.py`
- `backend/onyx/tools/tool_implementations/web_search/web_search_tool.py`
- `backend/onyx/tools/tool_implementations/web_search/clients/glomi_search_client.py`
- `backend/onyx/search_gateway/server.py`
- `backend/onyx/search_gateway/service.py`
- `backend/onyx/search_gateway/adapters.py`
- `backend/onyx/search_gateway/tavily.py`
- `backend/onyx/search_gateway/query_planner.py`

当前边界：

- `open_url` 仍使用 Onyx 默认内容抓取逻辑和 `OnyxWebCrawler` fallback。
- Gateway 的 `deep` 只是高召回检索，不等于完整 Deep Research。
- C 端用户不看到 provider/channel 配置。

### 4. Search Debug Drawer

目标：让开发/管理员看清一次搜索到底发生了什么，方便排障。

流式链路：

```text
WebSearchTool provider execution
  -> collect provider / mode / channel / queries / duration / results / failures
  -> emit search_tool_debug_delta
  -> frontend packet group keeps debug packet with search tool packets
  -> WebSearchToolRenderer FULL mode renders collapsed debug drawer
```

展示内容：

- provider type / name
- mode / channel
- queries
- duration
- result URLs
- failed queries
- error

安全边界：

- 不落库。
- 不发送 API key。
- 不发送 Authorization header。
- 不发送 Gateway base URL。
- 不作为普通用户配置入口。

关键文件：

- `backend/onyx/server/query_and_chat/streaming_models.py`
- `backend/onyx/tools/tool_implementations/web_search/web_search_tool.py`
- `web/src/app/app/services/streamingModels.ts`
- `web/src/app/app/services/packetUtils.ts`
- `web/src/app/app/message/messageComponents/timeline/renderers/search/*`

### 5. Craft 生成交付运行时

目标：把 Onyx Craft 从“独立 Build 工作台”改造成 GlomiAI 的王牌交付能力。短问答和研究仍走 chat / Deep Research；需要页面、PPT、报告、看板、小工具、可分享成品时才进入 Craft。

集成路线：

```text
User Chinese request
  -> chat main controller
  -> intent: answer / research / generate artifact
  -> answer: chat loop
  -> research: Deep Research
  -> generate artifact: Craft session
  -> sandbox preview / files / snapshots
  -> shareable artifact page
```

Phase B 顺序：

1. **稳定运行与资源治理**：明确 Docker Compose / 远端 Compose / k8s 形态，限制 sandbox 并发、CPU、内存、闲置回收和任务超时，避免单机 Linux 被预创建 sandbox 拖垮。
2. **独立 Craft C 端入口**：把原 Onyx 企业知识库语境改为中文消费级模板入口，如落地页、PPT、数据看板、报告、小工具。
3. **生成物分享闭环**：让 Craft 输出默认可以公开/私密分享，分享页隐藏工作台复杂性。
4. **主对话派发 Craft**：主控识别生成交付意图，创建或复用 Craft session，把进度、预览和最终产物回填到对话。

保留的 Craft 资产：

- sandbox 隔离和实时预览
- opencode-serve agent 执行链
- 文件系统、上传、快照和恢复
- skills / external apps / approvals 作为后续扩展底座

## 规划中的任务

### Phase B 当前任务

- **Craft 运行稳定性**：把资源治理作为第一优先级，解决 sandbox 启动、卡死、回收、日志和失败恢复。
- **Craft 模型适配**：让 Craft 复用平台模型目录，验证 OpenAI-compatible 模型在 opencode-serve 工具调用、streaming、长上下文下的兼容性。
- **Craft C 端化**：去订阅门控、沙箱镜像/网络国内化、消费级生成入口、模板化体验。
- **生成物分享**：把站点、PPT、数据看板、报告等生成结果做成可公开/私密分享页面。
- **超级编排层 E13**：主控自动判断聊天/研究/建站/代码任务，派子 agent 并行执行，再汇总结果。
- **搜索能力继续增强**：Gateway 多来源聚合、渠道 fallback、成本控制、source_type / score 展示、证据质量评估。

### Phase C 规划任务

- 微信扫码 / 手机号登录。
- 支付、套餐、积分或按量计费。
- 内容安全审核、实名、ICP、数据本地化。
- 国内云部署运维。
- 国内连接器：飞书、钉钉、语雀、企业微信。

## 这不是

- 不是 Onyx 企业知识库产品的简单换皮。
- 不是优先做鉴权、支付、计费、团队版和商业化后台。
- 不是让用户自己配置 LLM provider、搜索 provider 或复杂工具链。
- 不是把所有请求都塞进重型 sandbox。

Phase B 先把 Craft 作为生成交付运行时打磨出来。鉴权、支付、合规、国内云部署、连接器生态和正式商业化会在 Phase C 推进；公网前必须先做内容安全和合规 gate。

## 产品路线

| 阶段 | 目标 | 状态 |
|---|---|---|
| Phase A | 中文核心能力验证：i18n、平台模型、超级对话、深度研究、Glomi Search Gateway | 已完成核心验证 |
| Phase B | Craft C 端化、生成物分享、超级编排层 | 当前重心 |
| Phase C | 鉴权、计费、内容安全、国内云部署、商业化上线 | 延后 |

详细路线见 [docs/GlomiAI.md](docs/GlomiAI.md)。

## 架构骨架

```text
web/
  Next.js 前端，消费级体验改造和聊天 / 研究 / Craft 入口

backend/onyx/
  chat/                 普通对话 agent loop
  deep_research/        深度研究多 agent 工作流
  tools/                web_search、open_url、python、Craft 等工具系统
  llm/                  LLM provider 与 LiteLLM / OpenAI-compatible 集成
  db/                   数据库模型与操作，所有 DB 写法应收敛在这里
  search_gateway/       Glomi 本地搜索 Gateway，一期支持 Tavily channel
  server/               FastAPI API 层

backend/ee/
  上游企业版能力边界。GlomiAI 后续会按自己的 C 端需求剥离和重建。

docs/
  产品蓝图、设计文档、实施计划和工程记录
```

## 本地开发

### 依赖

Python 依赖由 `uv` 管理，虚拟环境位于仓库根目录 `.venv`。

```powershell
uv sync --frozen
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
uv sync --frozen
source .venv/bin/activate
```

前端依赖位于 `web/`。按现有 Onyx 开发方式使用 npm / bun，具体见 [web/README.md](web/README.md) 和 [CONTRIBUTING.md](CONTRIBUTING.md)。

### 环境变量

本地开发常用配置在 `.vscode/.env`。不要提交真实 API key。

平台模型目录 / 默认兼容模型：

```env
CONSUMER_DEFAULT_LLM_ENABLED=true
CONSUMER_DEFAULT_LLM_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
CONSUMER_DEFAULT_LLM_API_KEY=...
CONSUMER_DEFAULT_LLM_MODEL_NAME=qwen-plus
```

平台默认搜索：

```env
GLOMI_DEFAULT_WEB_SEARCH_ENABLED=true
GLOMI_DEFAULT_WEB_SEARCH_API_BASE=http://localhost:7777
GLOMI_DEFAULT_WEB_SEARCH_API_KEY=dev-gateway-key
GLOMI_DEFAULT_WEB_SEARCH_CHANNEL=tavily
```

测试和运行涉及真实模型调用时，按项目约定优先使用：

- OpenAI：`gpt-5-mini`
- Anthropic：`claude-haiku-4-5`

### 访问应用

默认前端地址：

```text
http://localhost:3000
```

本地常用登录：

```text
username: a@example.com
password: a
```

调用后端时优先走前端代理，例如：

```text
http://localhost:3000/api/persona
```

不要直接绕过到 `http://localhost:8080/api/...`，除非你明确知道自己在验证底层服务。

### 启动本地 Glomi Search Gateway

仓库内提供一个本地 FastAPI Gateway，便于用 Tavily API key 跑通平台默认搜索链路。

完整 Docker Compose 已内置 `search_gateway` 服务，容器内应使用：

```env
GLOMI_DEFAULT_WEB_SEARCH_API_BASE=http://search_gateway:7777
```

只有在本地源码直接跑 API / Gateway 时，才使用 `http://localhost:7777`。

```powershell
$env:PYTHONUTF8='1'
$env:GLOMI_SEARCH_GATEWAY_API_KEY='dev-gateway-key'
$env:GLOMI_SEARCH_GATEWAY_DEFAULT_CHANNEL='tavily'
$env:TAVILY_API_KEY='...'
.venv\Scripts\python.exe -m uvicorn onyx.search_gateway.server:app --host 0.0.0.0 --port 7777
```

健康检查：

```text
GET http://localhost:7777/health
```

## 常用验证

后端聚焦测试：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend/tests/unit
```

Glomi Search / Gateway 聚焦测试：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend/tests/unit/onyx/search_gateway backend/tests/unit/onyx/tools/tool_implementations/websearch
```

前端类型检查：

```powershell
cd web
npm run types:check
```

Playwright E2E：

```powershell
cd web
bunx playwright test <TEST_NAME>
```

如果修改 Celery worker，测试前需要人工重启对应 worker。Celery thread pool 下 time limit 不生效，超时逻辑必须在任务内部实现。

## 开发约束

- 所有相关变动都要记录到 [summary.md](summary.md)，包括坑、经验和验证记录。
- 产品路线或产品语义变化要同步更新 [docs/GlomiAI.md](docs/GlomiAI.md)。
- 数据库操作放在 `backend/onyx/db` 或 `backend/ee/onyx/db`。
- 新 FastAPI API 不使用 `response_model`，通过函数类型表达返回结构。
- 后端业务错误使用 `OnyxError`，不要直接抛 `HTTPException`。
- LLM、embedding、rerank、image、voice、intent classification 调用都必须用 `LLMFlow` tracing 标记。
- Celery task 使用 `@shared_task`，入队必须设置 `expires=`。
- Python 和 TypeScript 都要尽量严格类型化。
- 不提交密钥，不把真实 API key 写入文档或代码。

## 重要文档

- [GlomiAI 产品蓝图](docs/GlomiAI.md)
- [平台默认 OpenAI-compatible LLM Provider 设计](docs/superpowers/specs/2026-06-14-platform-default-openai-compatible-llm-design.md)
- [中文 Agent 搜索与研究能力层设计](docs/superpowers/specs/2026-06-13-agent-search-and-research-strategy-design.md)
- [平台默认 Glomi Search Gateway 与 Agent 搜索模式设计](docs/superpowers/specs/2026-06-15-platform-default-glomi-search-gateway-design.md)
- [本地 Glomi Search Gateway 设计](docs/superpowers/specs/2026-06-15-local-glomi-search-gateway-design.md)
- [Search Debug Drawer 设计](docs/superpowers/specs/2026-06-15-search-debug-drawer-design.md)
- [工程贡献指南](CONTRIBUTING.md)

## 来源与授权

GlomiAI 基于 Onyx 开源项目继续开发。Onyx Community Edition 的核心能力基于 MIT license，仓库仍保留上游授权和目录边界。

正式对外发布前，需要再次复核品牌、商标、企业版目录、第三方依赖和所有分发材料的授权表述。
