# 子项目 A 设计:build_runtime 地基 + 落地页端到端(Daytona + Pi)

- 日期:2026-06-22
- 状态:已批准,待写实现计划
- 所属大工程:GlomiAI Craft → 生成交付运行时(Daytona + Pi 重写)
- 上游设计稿:`docs/glomi/crfat-like/craft-arch.md`、`docs/glomi/crfat-like/inteface.md`
- 总体路线:见 `docs/superpowers/specs/2026-06-22-build-runtime-roadmap.md`

---

## 背景与关键决策

设计稿(v0.1 草案)主张以 **Daytona** 作沙箱底座、**Pi** 作沙箱内 builder harness,构建 GlomiAI 的生成交付运行时。当前代码库已有一套成熟的 Craft 等价物(`server/features/build`:`SandboxManager` 抽象 + Docker/K8s 后端 + **opencode** builder + BuildSession/Sandbox/Artifact 模型 + snapshot/preview/streaming),仓库内无任何 Daytona/Pi 引用。

经确认,采用以下决策:

1. **底座方向**:彻底换成 Daytona + Pi。用 strangler 策略 —— 新 `build_runtime` 模块与现有 opencode/Docker 并行搭建、逐步切流,避免一次性砸掉可用代码。
2. **Daytona 部署**:自托管(开源 AGPL 3.0,Helm 部署到国内 k8s 可行)。**仅通过 SDK/API 调用、不改 Daytona 源码**,以规避 AGPL 传染到 GlomiAI 代码。国内 k8s 生产部署归独立基础设施子项目;A 开发期先用 Daytona 本地 docker-compose 全栈。
3. **第一个 spec = 子项目 A**:地基 + 1 个落地页模板端到端打通。
4. **模块/数据**:全新并行模块 `backend/onyx/build_runtime/` + 新 DB 表 + feature flag;现有 Craft 不动。
5. **Pi 模型接入**:复用 GlomiAI 平台模型目录,把 OpenAI-compatible provider 映射成 Pi 的 `openai` provider。
6. **A 前端范围**:最小内测触发入口 + 复用现有 Craft 预览/streaming UI。

---

## Issues to Address(本次要解决的问题)

证明 Daytona + Pi 路径可端到端跑通,并沉淀可复用的领域模型与接口地基:

- 把自然语言交付需求转成结构化 `BuildSpec`。
- 用 Daytona 自托管沙箱 + Pi builder,从 `glomi-landing-page` 模板构建出一个可预览的 Next.js 落地页。
- 通过 Daytona proxy 暴露预览 URL,事件流回填 `BuildRuntimeSession` 状态,复用现有 Craft 预览 UI 展示。
- 沉淀 `SandboxProvider` / `BuilderAdapter` Protocol 与 `BuildOrchestrator` 状态机,作为后续 B/C/D/E 的复用底座。

**A 不做**:stop/resume/archive 生命周期治理(B)、Slides/Report/Dashboard 模板(C)、Reviewer 与发布/分享闭环(D)、主控意图路由(E)、evidence/research 接入(A 阶段落地页只从 `BuildSpec` + 用户上传构建)。

---

## Important Notes(来自代码库研究的非显然结论)

- **DB 操作位置**:CLAUDE.md 要求「所有 db 操作放 `backend/onyx/db` / `backend/ee/onyx/db`」。现有 `server/features/build/db/` 其实是一处偏差;新模块按 CLAUDE.md 走 —— SQLAlchemy 表进 `onyx/db/models.py`,DB 操作进 `onyx/db/build_runtime.py`,**不**沿用旧偏差。
- **枚举命名冲突**:`onyx/db/enums.py` 已有 `BuildSessionStatus`(归 opencode Craft 用)。新状态枚举命名须避开,用 `BuildRuntimeStatus`。
- **ORM 与 API model 分离**(inteface.md 原则):领域对象用 Pydantic 放 `build_runtime/schemas`;持久化用 SQLAlchemy;两者不混写,领域对象以 JSON 列承载(`spec`、`latest_output`、`last_error`)。
- **Daytona 架构特点**:它不用 k8s 直接跑沙箱,而是 k8s 跑 node、自有 orchestrator 在 node 上跑沙箱;自托管全栈含 api/runner/proxy/ssh-gateway/Postgres/Redis/Dex/Registry,最低 4 vCPU / 16GB / 200GB。这是一层不轻的新基础设施。
- **Pi 特性**:Node/TS,RPC + SDK 一等模式,provider-agnostic / BYO-key(含自托管 Qwen),贴合平台模型目录;**自身无沙箱与权限隔离,必须容器化** —— 由 Daytona 兜住。License 实现时须查 LICENSE 文件确认。
- **AGPL 边界**:Daytona 部署不改源、经 SDK/API 调用 → GlomiAI 非衍生作品。`glomi-landing-page` snapshot 镜像内容(模板 + Pi)是我们自己的资产。
- **LLM tracing**:`SpecBuilder` 的 NL→Spec 调用须新增 `LLMFlow.BUILD_SPEC_GENERATION` 并开 generation span(CLAUDE.md tracing 规则)。
- **错误处理**:统一 `OnyxError`,新增错误码到 `onyx/error_handling/error_codes.py`(`BUILD_PROVISION_FAILED`、`BUILDER_FAILED`),不用 `HTTPException`,不用 `response_model`。
- **Celery 规则**:驱动 provisioning 的后台任务用 `@shared_task`、放 `background/celery/tasks/`、enqueue 必带 `expires=`,超时在任务内自行实现。

---

## Implementation Strategy(高层实现策略)

### 模块结构
```
backend/onyx/build_runtime/
  schemas/      build_session.py / build_spec.py / output_manifest.py / events.py / sandbox.py / builder.py
  interfaces/   sandbox_provider.py (Protocol) / builder_adapter.py (Protocol)
  providers/    sandbox/daytona_provider.py / builder/pi_builder_adapter.py
  services/     build_orchestrator.py / spec_builder.py / template_service.py
  templates/    landing_page/  (AGENTS.md, SYSTEM.md, output_contract, snapshot 引用)
  configs.py    feature flag (ENABLE_BUILD_RUNTIME) / Daytona endpoint / 默认模板
backend/onyx/db/build_runtime.py                      ← DB 操作
backend/onyx/db/models.py                             ← 新表 BuildRuntimeSession
backend/onyx/db/enums.py                              ← BuildRuntimeStatus 等
backend/onyx/server/features/build_runtime/api.py     ← 薄 API 路由
backend/onyx/background/celery/tasks/build_runtime/   ← 驱动 provisioning 的 @shared_task
```

### 数据模型
新表 `build_runtime_session`:`id`、`parent_chat_session_id`、`user_id`、`org_id?`、`artifact_type`、`template_id`/`template_version`、`title`、`status`(`BuildRuntimeStatus`:queued → provisioning → building → preview_ready → awaiting_feedback → completed / failed / terminated)、`spec`(JSON=BuildSpec)、`sandbox_provider`、`sandbox_id`、`builder_session_id`、`preview_url`、`latest_output`(JSON=OutputManifest)、`retry_count`、`last_error`(JSON=BuildError)、`created_at`/`updated_at`/`completed_at`/`terminated_at`。版本/工件 A 阶段用 JSON 承载,不拆独立版本表(留给 D)。Alembic 迁移手写迁移内容。

### 接口与实现
- **`SandboxProvider` Protocol**:create_sandbox / get_sandbox_status / write_files / read_files / run_command / stream_logs / expose_preview / stop / resume / archive / delete(对齐 inteface.md §2.2)。
- **`DaytonaSandboxProvider`**:Daytona Python SDK 连自托管 control plane(endpoint 走 env);从 `glomi-landing-page` snapshot 起沙箱。snapshot = 预装 Node + Next.js + Tailwind/shadcn + Pi 的 OCI 镜像。
- **`BuilderAdapter` Protocol** + **`PiBuilderAdapter`**:经 Daytona exec 在沙箱内以 RPC 模式起 Pi,喂 `task.json`,订阅 Pi JSON 事件流并归一化成 `BuilderEvent`(builder_started / message_delta / file_changed / preview_ready / artifact_ready / build_blocked / builder_failed / builder_finished,对齐 inteface.md §3.1)。
- **模型接入**:`template_service` + adapter 把平台模型目录里的 OpenAI-compatible provider 映射成 Pi 的 `openai` provider,短时注入 key 到沙箱 env。
- **`SpecBuilder`**:NL→`BuildSpec`,LLM structured output;新增 `LLMFlow.BUILD_SPEC_GENERATION`。
- **`BuildOrchestrator`** 状态机(中枢):创建 session → `template_service` 解析 landing_page → `provider.create_sandbox(snapshot)` → 写入 `task.json/AGENTS.md/SYSTEM.md` → `adapter.start_build` → 消费 `BuilderEvent` 回写 session 状态 → `expose_preview` 写 `preview_url` → `builder_finished` 写 OutputManifest + status=completed;失败 → `last_error` + status=failed,硬失败 terminate 沙箱。

### 执行与数据流(推荐)
`POST` 立即建 session 并入队 Celery `@shared_task`(带 `expires=`)驱动 provisioning + start;`GET …/events` SSE 端点 attach 到该构建,relay `BuilderEvent` + session 状态。SSE 复用现有 `sandbox/sse.py` keepalive。
> 备选(不推荐):整段同步 streaming —— provisioning 阻塞首字节、断线难恢复。

### API(薄路由)
- `POST /api/build-runtime/sessions` — 建 + 启
- `GET /api/build-runtime/sessions/{id}` — 查询
- `POST /api/build-runtime/sessions/{id}/instruction` — 继续改
- `POST /api/build-runtime/sessions/{id}/terminate` — 终止
- `GET /api/build-runtime/sessions/{id}/events` — SSE 进度流

统一 `OnyxError`,不用 `response_model`,前端经 `localhost:3000/api/...` 走。

### 前端(最小)
feature flag 后的内测触发入口,调用新 API + 复用现有 Craft 预览 iframe 组件 + 订阅 SSE 显示进度。不做双通道消费级 UI(留给 E)。前端遵守 `web/AGENTS.md`:Opal 优先、`@/` 绝对导入、自定义 Tailwind 颜色变量、`function` 语法。

### A 内含的 spike(前置)
A 第一步先用 Daytona 本地 docker-compose 全栈打通(起沙箱 + 跑 Pi 构建 + 拿 preview URL),再补地基与编排。国内 k8s 生产部署归独立基础设施子项目(见路线图)。

---

## Tests(测试策略,不过度测)

- **单元(核心)**:`BuildOrchestrator` 状态机 —— 用 `FakeSandboxProvider` / `FakeBuilderAdapter`(Protocol 让 mock 很轻),验证状态流转、`BuilderEvent`→session 映射、失败归类与清理。`mock` 一切外部依赖。
- **e2e(外部依赖,env 门控)**:对真实 dev Daytona + Pi 跑一次落地页 happy path,断言 preview URL 可达 + OutputManifest 完整。无 Daytona endpoint 时跳过。
- **SpecBuilder**:一条真实 LLM(`gpt-5-mini`)测试,中文落地页 prompt → 合法 `BuildSpec`。

通常以上三类足够;不为每个 provider 方法写独立 e2e。

---

## 验收标准

1. `POST /api/build-runtime/sessions` 传一段中文落地页需求 → 返回 session,状态依次走到 `preview_ready`/`completed`。
2. `GET …/events` 能流式看到 `BuilderEvent` 进度。
3. 拿到的 `preview_url` 能打开一个可见的 Next.js 落地页。
4. `BuildOrchestrator` 单元测试全绿;一条 SpecBuilder LLM 测试绿;e2e happy path 在有 Daytona 时绿。
5. 现有 opencode Craft 不受影响(feature flag 关闭时零行为变化)。
