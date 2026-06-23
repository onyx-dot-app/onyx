下面是一版可直接拿去继续细化的草案。

---

# 《[GlomiAI](https://www.genspark.ai/api/files/s/QDdMm4Pf) × [Daytona](https://www.daytona.io/docs/architecture/) × [Pi](https://pi.dev/) Glomi Forge 架构草案 v0.1》

## 0. 文档定位

本文定义 GlomiAI 自研“Glomi Forge runtime”的第一版总体架构：
以 **GlomiAI 主控智能体** 为统一入口，以 **Daytona** 作为 sandbox/runtime substrate，以 **Pi** 作为 sandbox 内 builder harness，构建一个面向“页面、PPT、报告、看板、小工具”等交付物的生成运行时。该方案的核心目标，是**取消 Onyx Craft 作为用户可见独立功能的产品心智**，但保留其“独立执行会话 + 隔离环境 + 可预览 + 可继续编辑”的能力模型。这个方向与当前 GlomiAI Phase B“把 Craft 改造成生成交付运行时，并由主控识别生成交付意图后派发执行”的路线一致。[Source](https://www.genspark.ai/api/files/s/QDdMm4Pf)

---

## 1. 愿景与设计目标

### 1.1 产品愿景

用户只面对 **一个 GlomiAI 主控入口**。  
主控根据意图自动决定：

- 普通问答 → chat loop
- 深度研究 → research loop
- 交付物生成 → forge loop

对于交付物场景，系统自动创建 ForgeSession，选择模板，启动 builder，在对话中同步进度，并在画布中展示预览与最终成品，而不是把用户跳转到一个独立的 Craft 产品页。[Source](https://www.genspark.ai/api/files/s/QDdMm4Pf)

### 1.2 设计目标

本方案 v0.1 的目标：

1. **统一入口**：前台取消独立 Craft 心智，交付物能力收归主控。
2. **运行隔离**：重型 build 不进入主 chat loop，而进入独立 runtime。
3. **状态持续**：交付物支持继续修改、暂停恢复、归档、发布。
4. **模板优先**：先围绕少量高成功率模板落地，而不是一开始做万能环境。
5. **可替换底座**：Daytona/Pi 是实现，不绑定为唯一不可替换方案。
6. **可演进治理**：支持资源限制、空闲回收、日志、失败恢复、审查与分享。

---

## 2. 非目标

v0.1 暂不追求：

- 通用无限制多智能体系统
- 所有任务自动拆成并行子 agent
- 用户级自定义 sandbox 镜像市场
- 任意语言/任意系统环境的全覆盖
- 完整 CI/CD 或生产部署平台
- 强依赖 Onyx Craft 原模块代码路径

v0.1 重点是：**先把“统一主控下的交付物运行时”跑通并跑稳。**

---

## 3. 总体设计原则

### 3.1 产品层合并，执行层分离

用户体验上只有一个 GlomiAI。  
系统内部必须保留独立的 ForgeSession、Sandbox、Workspace、Preview、Review、Publish 机制。

### 3.2 主控负责编排，不直接做重执行

GlomiAI 主控负责：

- 意图识别
- 任务规格化
- 模板选择
- 研究材料整理
- 创建/恢复 ForgeSession
- 与用户持续交互
- 结果汇总与发布

GlomiAI 主控**不直接承担**：

- 运行代码
- 维护进程环境
- 管理预览端口
- 管理 sandbox 生命周期

### 3.3 Daytona 做 runtime substrate

Daytona 官方架构将平台分为 interface plane、control plane、compute plane；其中 control plane 负责 sandbox 生命周期与资源调度，compute plane 负责 runner、sandbox daemon、snapshot、volume 等基础能力。这非常适合映射到 GlomiAI 的 Glomi Forge runtime 底座。[Source](https://www.daytona.io/docs/architecture/)

### 3.4 Pi 做 builder harness，不做总控

Pi 官方定位是 minimal agent harness，擅长 extensions、skills、prompt templates、SDK/RPC 等 agent 内核能力；同时它明确说明自己**没有 built-in sandbox**，真正隔离需要来自容器、VM、micro-VM 或远程 sandbox。因此 Pi 最适合放进 Daytona sandbox 中运行，担任单个 ForgeSession 内的 builder agent。[Source](https://pi.dev/) [Source](https://pi.dev/docs/latest/security)

---

## 4. 总体架构

## 4.1 逻辑分层

```text
┌──────────────────────────────────────────────┐
│                GlomiAI Frontend              │
│  Chat UI / Canvas / Preview / Share Page    │
└──────────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│           GlomiAI Main Controller            │
│ intent / routing / spec / evidence / review  │
└──────────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│         Forge Orchestrator (Forge Core)      │
│ ForgeSession / template / lifecycle / logs   │
└──────────────────────────────────────────────┘
           │                          │
           │                          │
           ▼                          ▼
┌───────────────────────┐   ┌───────────────────────┐
│ Daytona Provider      │   │ Pi Adapter            │
│ sandbox/snapshot/     │   │ rpc/session/events/   │
│ volume/proxy/lifecycle│   │ builder control       │
└───────────────────────┘   └───────────────────────┘
           │                          │
           └──────────────┬───────────┘
                          ▼
┌──────────────────────────────────────────────┐
│            Daytona Sandbox Runtime           │
│ workspace / preview / files / pi process     │
└──────────────────────────────────────────────┘
```

---

## 4.2 关键角色划分

### [GlomiAI](https://www.genspark.ai/api/files/s/QDdMm4Pf)
统一用户入口与主控编排层。负责“何时进入交付物模式”。

### [Daytona](https://www.daytona.io/docs/architecture/)
负责 sandbox 生命周期、snapshot、volume、proxy、runner、环境隔离与持久化。[Source](https://www.daytona.io/docs/architecture/)

### [Pi](https://pi.dev/)
负责在 sandbox 内作为 coding agent/build harness 执行构建任务，通过 extensions/skills/prompt templates 实现模板能力。[Source](https://pi.dev/)

---

## 5. 核心对象模型

## 5.1 `ForgeSession`

`ForgeSession` 是本架构的一等公民。
它代表“一次由主控派发出来的交付物构建任务”。

建议字段：

```ts
type ForgeSession = {
  id: string
  parentChatSessionId: string
  userId: string
  orgId?: string

  intentType: "artifact_generation"
  artifactType: "landing_page" | "slides" | "report" | "dashboard" | "tool"
  templateId: string
  templateVersion: string

  status:
    | "queued"
    | "provisioning"
    | "building"
    | "awaiting_feedback"
    | "reviewing"
    | "publishing"
    | "completed"
    | "failed"
    | "archived"
    | "terminated"

  spec: ForgeSpec
  evidencePackRef?: string

  sandboxProvider: "daytona"
  sandboxId?: string
  previewUrl?: string

  piSessionId?: string
  outputManifest?: OutputManifest
  reviewResult?: ReviewResult

  createdAt: string
  updatedAt: string
}
```

## 5.2 `ForgeSpec`

主控将自然语言需求转成结构化 spec，再交给 builder。

```ts
type ForgeSpec = {
  title: string
  goal: string
  targetAudience?: string
  artifactRequirements: string[]
  visualStyle?: string
  brandConstraints?: string[]
  dataSources?: string[]
  outputFormat: string[]
  acceptanceCriteria: string[]
}
```

## 5.3 `OutputManifest`

```ts
type OutputManifest = {
  primaryArtifactPath: string
  previewEntry?: string
  downloadableFiles: string[]
  screenshots?: string[]
  metadata?: Record<string, string>
}
```

---

## 6. 主流程设计

## 6.1 端到端流程

```text
用户提出需求
  -> 主控识别为交付物需求
  -> 主控生成 ForgeSpec
  -> 主控整理 Evidence Pack
  -> Forge Orchestrator 创建 ForgeSession
  -> Daytona 创建 Sandbox（基于选定 template snapshot）
  -> 挂载 workspace/evidence/assets volumes
  -> 写入 task.json / AGENTS.md / SYSTEM.md
  -> 启动 Pi builder
  -> Pi 构建交付物
  -> Daytona Proxy 暴露预览 URL
  -> 前端 Canvas 展示预览与进度
  -> Reviewer 验收
  -> 回填主会话
  -> 用户继续修改或发布归档
```

## 6.2 主控与 ForgeSession 的关系

主控永远是用户可见主体。  
ForgeSession 是后台任务实例。用户看到的是：

- “我已开始生成”
- “正在构建预览”
- “这里是当前结果”
- “我已根据你的反馈继续修改”

用户不需要理解 Daytona 或 Pi 的存在。

---

## 7. [Daytona](https://www.daytona.io/docs/architecture/) 集成设计

## 7.1 集成定位

Daytona 在本方案中作为 `SandboxProvider` 实现，负责：

- 创建 sandbox
- 从 snapshot 启动
- 挂载 volumes
- 提供 preview 访问
- 提供 sandbox lifecycle API
- 提供自动 stop/archive/delete 策略

Daytona 的 control plane 与 compute plane 结构使其非常适合承载这类“可继续编辑的交付会话”。[Source](https://www.daytona.io/docs/architecture/)

---

## 7.2 生命周期映射

Daytona 文档定义了丰富的 sandbox 生命周期：Creating、Started、Stopped、Archived 等，并支持 ephemeral、auto-stop、auto-archive 等策略。[Source](https://www.daytona.io/docs/en/sandboxes/)

建议映射如下：

| GlomiAI ForgeSession | Daytona Sandbox 状态 |
|---|---|
| provisioning | Creating / Starting |
| building | Started |
| awaiting_feedback | Paused 或 Stopped |
| resumable_idle | Stopped |
| dormant | Archived |
| completed_short_term | Stopped / Archived |
| throwaway_preview | Ephemeral |
| terminated | Deleted |

### 设计建议
- 快速试跑/失败重试场景可用 **ephemeral**
- 用户可能回来继续改的任务优先用 **stopped**
- 长时间不用但需保留成品和源码的任务用 **archived**
- 长交互中的极短暂停可考虑 **paused**（仅在确有内存态价值时使用）[Source](https://www.daytona.io/docs/en/sandboxes/)

---

## 7.3 Snapshot 模板系统

Daytona snapshots 是基于 Docker/OCI 的可复用 sandbox 模板，用于定义基础 OS、runtime、系统包与项目级 setup，避免每次重复 bootstrap。[Source](https://www.daytona.io/docs/en/snapshots/)

v0.1 建议只做 4 个模板：

### `glomi-landing-page`
- Node.js
- Next.js / React
- Tailwind / shadcn
- 适用：品牌页、营销页、活动页

### `glomi-slides`
- Node.js
- PptxGenJS / Marp
- 图表与导出依赖
- 适用：PPT、deck、方案提案

### `glomi-report`
- Python + Markdown/HTML/PDF
- 适用：研究报告、行业分析、白皮书

### `glomi-dashboard`
- Python + pandas + charting + web serving
- 适用：可视化报告、数据看板、小工具

### 模板不只是环境
每个 template 还绑定：
- snapshot
- 默认目录结构
- 默认 AGENTS.md / SYSTEM.md
- 默认 output contract
- 默认 reviewer rules

---

## 7.4 Volume 设计

Daytona volumes 提供跨 sandbox 共享与持久化存储，数据独立于 sandbox 生命周期，支持 `subpath` 隔离，很适合多租户和多会话场景。[Source](https://www.daytona.io/docs/en/volumes/)

建议拆成三类：

### 1. `shared-assets`
用途：
- 品牌资源
- 公共组件
- 内部模板
- 静态素材

挂载：
- `/mnt/assets`

### 2. `workspace-state`
用途：
- 当前源码
- 中间产物
- 构建日志
- review 输出

挂载：
- `/workspace`

### 3. `evidence-pack`
用途：
- 主控整理的研究材料
- 用户上传文件
- 数据源快照
- 引用内容

挂载：
- `/mnt/evidence`

### 原则
- 共享资产与会话状态分离
- evidence 与 workspace 分离
- 每个用户/会话通过 `subpath` 做隔离 [Source](https://www.daytona.io/docs/en/volumes/)

---

## 7.5 Preview 接入

Daytona control plane 中的 proxy 支持将 sandbox 内服务通过 host-based routing 暴露为可访问地址，适合承载交付物预览。[Source](https://www.daytona.io/docs/architecture/)

在 GlomiAI 中：
- preview URL 不直接暴露底层细节
- 前端通过 Canvas iframe / webview 渲染
- 主控对话中同步“预览已生成”

---

## 8. [Pi](https://pi.dev/) 集成设计

## 8.1 Pi 角色定位

Pi 是 **sandbox 内的 builder harness**。  
不承担：
- 产品主控
- 生命周期治理
- 多模板路由
- 用户会话存储

承担：
- 读取 task spec
- 读取 AGENTS.md / SYSTEM.md
- 在 workspace 中执行编码任务
- 调用内建工具与自定义扩展
- 输出事件流、日志、文件结果

Pi 官方提供 extensions、skills、prompt templates、RPC、SDK 等机制，非常适合作为这层 builder 引擎。[Source](https://pi.dev/)

---

## 8.2 集成模式选择

Pi SDK 文档指出：
- **SDK** 适合同进程 Node.js 深度集成
- **RPC** 适合跨语言、需要进程隔离的场景 [Source](https://pi.dev/docs/latest/sdk)

### v0.1 结论
优先采用 **Pi RPC / 独立进程模式**。

原因：
1. 与现有 GlomiAI 主控更解耦
2. 故障隔离更好
3. 易于让 Pi 作为 sandbox 内独立 builder 进程运行
4. 避免把主控硬迁入 Node 进程

---

## 8.3 Pi 运行边界

Pi 安全文档明确说明：  
Pi **没有 built-in sandbox**，它默认以启动进程的权限运行；真正隔离要靠容器、VM、micro-VM 或远程 sandbox。[Source](https://pi.dev/docs/latest/security)

因此本方案要求：

> **Pi 整个进程必须运行在 Daytona sandbox 内。**

而不是：
- 在宿主机运行 Pi 再把工具映射进 sandbox
- 让 Pi 直接接触宿主机文件系统或长期密钥

Pi 的 containerization 文档也支持“整个 pi 进程跑在隔离环境里”的模式，这与 Daytona 组合最契合。[Source](https://pi.dev/docs/latest/containerization)

---

## 8.4 Pi 资源组织方式

每个 template 在 sandbox 内都写入：

```text
/workspace
  /input
    task.json
    evidence_pack.json
    uploads/
  /context
    AGENTS.md
    SYSTEM.md
    template_rules.md
  /src
  /out
  /logs
  /review
```

### 文件职责

- `task.json`：主控输出的结构化任务规格
- `evidence_pack.json`：研究材料与结构化素材
- `AGENTS.md`：模板级操作规范
- `SYSTEM.md`：builder 的系统提示补充
- `/src`：构建源码
- `/out`：最终交付物
- `/logs`：Pi 运行与构建日志
- `/review`：review 结果

---

## 8.5 Pi Extensions / Skills 设计

Pi 最值得利用的是它的扩展体系。

### 建议内置 Skills
- `build-landing-page`
- `build-slides`
- `build-report`
- `build-dashboard`
- `verify-output`
- `publish-preview`

### 建议内置 Extensions
- `emit-build-progress`
- `submit-artifact`
- `sync-preview-url`
- `restrict-workspace-paths`
- `load-evidence-pack`
- `report-review-status`

这些可以把 Pi 的执行过程稳定映射回 GlomiAI 的 timeline 和 ForgeSession 状态。

---

## 9. GlomiAI 主控与 Builder 的协议

## 9.1 主控下发给 Pi 的最小协议

建议用结构化 JSON：

```json
{
  "task_id": "build_xxx",
  "artifact_type": "landing_page",
  "title": "产品发布页",
  "goal": "生成一页式中文产品营销落地页",
  "requirements": [
    "包含 Hero 区、核心卖点、FAQ、CTA",
    "整体风格偏科技感",
    "移动端适配"
  ],
  "acceptance_criteria": [
    "页面可运行预览",
    "核心模块完整",
    "文案为中文",
    "输出 index route"
  ],
  "inputs": {
    "evidence_pack": "/mnt/evidence/evidence_pack.json",
    "assets_path": "/mnt/assets",
    "workspace": "/workspace"
  }
}
```

## 9.2 Pi 回传给主控的最小协议

建议统一事件语义：

- `build_started`
- `progress_update`
- `file_written`
- `preview_ready`
- `build_blocked`
- `build_completed`
- `build_failed`

这样主控就能在对话流中自然显示进度。

---

## 10. Reviewer 机制

v0.1 不建议一开始就做复杂多 agent。  
建议只保留两类后台 agent：

### 1. Builder
进入 Daytona + Pi 的执行器。

### 2. Reviewer
不承担重执行，仅检查：
- 是否符合 spec
- 是否符合 acceptance criteria
- 是否缺模块
- 是否引用了 evidence
- 是否需要返工

Reviewer 的输出进入 `/review` 并回填到 ForgeSession。

---

## 11. 安全与治理

## 11.1 权限原则

由于 Pi 没有内建 sandbox，权限边界必须依赖 Daytona。[Source](https://pi.dev/docs/latest/security)

原则：
- Pi 只在 Daytona sandbox 内运行
- sandbox 只挂载必要 volumes
- 不给 Pi 宿主机读写权限
- 平台密钥短时注入、最小授权
- 可由主控代替 builder 访问高敏感服务

## 11.2 网络原则

- 默认最小化出站访问
- template 级配置网络白名单
- 对无需联网模板，优先关闭外网访问
- 研究尽量在主控层完成，builder 只消费 evidence pack

## 11.3 生命周期治理

利用 Daytona 生命周期能力：
- auto-stop：空闲后自动 stop
- auto-archive：长时间 stop 后自动 archive
- throwaway 任务直接 ephemeral [Source](https://www.daytona.io/docs/en/sandboxes/)

---

## 12. 前端交互设计

## 12.1 用户视角

用户不进入 Craft 页面，只看到：

- 对话里出现“开始生成”
- 右侧或底部出现 Canvas
- 进度与日志逐步更新
- 预览生成后可直接查看
- 用户继续用自然语言修改

## 12.2 主控与画布协同

建议前端采用“双通道”：

- **Chat Stream**：主控解释、总结、确认变更
- **Canvas Stream**：预览、构建进度、版本结果

这样既保留对话感，也能保留交付物的可视化工作区体验。

---

## 13. 版本与发布策略

每个 ForgeSession 至少支持：

- 初始构建版本
- 后续修改版本
- 最终发布版本

建议数据对象：

- `draft versions`
- `published version`
- `archived source state`

preview 与 artifact 分离：
- preview 是运行态 URL
- artifact 是发布态文件或页面包

---

## 14. MVP 落地顺序

## Phase 1：Landing Page 单模板跑通
目标：
- 主控识别交付物意图
- Daytona 起 sandbox
- Pi 构建页面
- 前端显示 preview
- 用户自然语言继续修改

## Phase 2：加入 stop/resume/archive
目标：
- 支持 ForgeSession 恢复
- 支持用户次日继续改
- 控制资源成本

## Phase 3：加入 Slides / Report 模板
目标：
- 扩展交付物类型
- 验证 template system

## Phase 4：加入 Reviewer 与发布闭环
目标：
- 自动验收
- 自动导出/分享
- 版本化管理

---

## 15. 最小接口草案

## 15.1 `SandboxProvider`

```ts
interface SandboxProvider {
  createSandbox(input: CreateSandboxInput): Promise<CreateSandboxResult>
  resumeSandbox(sandboxId: string): Promise<void>
  stopSandbox(sandboxId: string): Promise<void>
  archiveSandbox(sandboxId: string): Promise<void>
  deleteSandbox(sandboxId: string): Promise<void>

  mountVolumes(sandboxId: string, mounts: VolumeMount[]): Promise<void>
  writeFiles(sandboxId: string, files: SandboxFile[]): Promise<void>
  readFiles(sandboxId: string, paths: string[]): Promise<SandboxFile[]>

  getPreviewUrl(sandboxId: string, port: number): Promise<string>
  getLogs(sandboxId: string): Promise<string>
}
```

## 15.2 `BuilderAdapter`

```ts
interface BuilderAdapter {
  startBuild(input: StartBuildInput): Promise<StartBuildResult>
  sendInstruction(sessionId: string, message: string): Promise<void>
  subscribe(sessionId: string, onEvent: (event: ForgeEvent) => void): Unsubscribe
  stop(sessionId: string): Promise<void>
}
```

---

## 16. 核心技术决策

### 决策 1：前台取消独立 Craft 入口
保留统一主控产品心智。

### 决策 2：后台保留独立 ForgeSession
避免把重型运行态揉进 chat loop。

### 决策 3：Daytona 做 runtime substrate
利用其 lifecycle、snapshots、volumes、proxy 能力。[Source](https://www.daytona.io/docs/architecture/) [Source](https://www.daytona.io/docs/en/sandboxes/) [Source](https://www.daytona.io/docs/en/snapshots/) [Source](https://www.daytona.io/docs/en/volumes/)

### 决策 4：Pi 用 RPC/独立进程模式
优先追求隔离、稳定、可替换性。[Source](https://pi.dev/docs/latest/sdk)

### 决策 5：Pi 整体运行在 Daytona sandbox 内
不允许裸跑在宿主机上。[Source](https://pi.dev/docs/latest/security) [Source](https://pi.dev/docs/latest/containerization)

### 决策 6：模板优先，不做万能环境
先做 4 个高成功率模板。

---

## 17. 当前已知风险

1. **Pi 扩展体系需要一定 TS 工程能力**  
   这会增加 builder 侧定制开发成本。

2. **Daytona 接入会引入新的基础设施治理面**  
   包括 runner、volume、snapshot、proxy 管理。

3. **预览与发布分离会增加前端状态管理复杂度**  
   但这是必要复杂度。

4. **主控如果不做结构化 spec，会把 builder 提示词搞得很脆弱**  
   因此 ForgeSpec 必须是核心对象。

5. **研究材料如果不先整理成 evidence pack，builder 会被过长上下文污染**  
   所以 research 应优先在主控侧完成。

---

## 18. v0.1 结论

本草案建议 GlomiAI 采用如下定位：

- **GlomiAI**：统一入口与主控编排层
- **Daytona**：Glomi Forge 的 runtime substrate
- **Pi**：sandbox 内 builder harness
- **Onyx Craft**：仅作为参考对象，不作为最终用户产品形态

最终目标不是“再做一个 Craft 页面”，而是：

> **让交付物能力成为 GlomiAI 主控背后的默认生成引擎。**

这与当前 GlomiAI 的产品方向、Daytona 的 runtime 能力、以及 Pi 的 agent harness 定位是高度一致的。[Source](https://www.genspark.ai/api/files/s/QDdMm4Pf) [Source](https://www.daytona.io/docs/architecture/) [Source](https://pi.dev/)

---

## 参考图示

### Daytona 架构图
![Daytona Architecture](https://www.daytona.io/docs/_astro/architecture-light.BnM5ncyi.svg)  
来源：[Daytona Architecture](https://www.daytona.io/docs/architecture/)

### Daytona 生命周期图
![Daytona Sandbox Lifecycle](https://www.daytona.io/docs/_astro/sandbox-states.CPW4fTyb.svg)  
来源：[Daytona Sandboxes](https://www.daytona.io/docs/en/sandboxes/)

### Onyx Craft 参考界面
![Onyx Craft UI](https://mintcdn.com/danswer/tPwPV81tzzmsOpmY/assets/overview/core_features/craft.png?fit=max&auto=format&n=tPwPV81tzzmsOpmY&q=85&s=0e4c93f439ce7673051822a000e68707)  
来源：[Onyx Craft](https://docs.onyx.app/overview/core_features/craft)

---
