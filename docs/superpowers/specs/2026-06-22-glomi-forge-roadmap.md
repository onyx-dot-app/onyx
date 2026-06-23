# Glomi Forge → 生成交付运行时(Daytona + Pi)推进路线图

- 日期:2026-06-22
- 状态:活文档(随各子项目推进更新)
- 配套 spec:`docs/superpowers/specs/2026-06-22-glomi-forge-daytona-pi-design.md`(子项目 A)
- 上游设计稿:`docs/glomi/forge/forge-arch.md`、`docs/glomi/forge/interfaces.md`
- 关联产品路线:`docs/GlomiAI.md`(Phase B,E5/E6/E13)

---

## 总目标

把现有 Craft(opencode + Docker/K8s 沙箱)逐步替换为以 **Daytona**(自托管沙箱底座)+ **Pi**(沙箱内 builder harness)为底座的 GlomiAI 生成交付运行时,最终让交付物能力成为主控背后的默认生成引擎,而非用户可见的独立 Craft 工作台。

**策略主线:strangler(并行替换)。** 新 `glomi_forge` 模块与现有 Craft 并存,feature flag 控制,逐子项目切流;每个子项目独立 spec → 计划 → 实现 → 验收,可单独上线、可回退到旧 Craft。

---

## 节点总览

| 节点 | 名称 | 目标 | 依赖 | 退出标准 |
|---|---|---|---|---|
| **A** | glomi_forge 地基 + 落地页端到端 | 证明 Daytona+Pi 路径可端到端跑通,沉淀领域模型/接口/编排地基 | 无 | 一段中文需求 → Daytona 沙箱 → Pi 构建落地页 → 预览可开;编排单测绿 |
| **INFRA** | Daytona 国内自托管 | 把 Daytona 全栈部署到国内 k8s,生产可用 | A 的 spike | 国内 k8s 上 Daytona 全栈稳定,GlomiAI 能连;镜像/网络国内化 |
| **B** | 生命周期 + 资源治理 | stop/resume/archive + 限额/空闲回收/失败恢复 | A、INFRA | 用户次日可继续改;并发/空闲/CPU 内存受控;有可观测日志 |
| **C** | 模板扩展 | Slides / Report / Dashboard 模板 | A、B | 至少 3 个新模板端到端跑通,template system 经验证 |
| **D** | Reviewer + 发布/分享闭环 | 自动验收 + 公开/私密分享页 + 版本化 | A、B、C | 产物可自动验收、导出、生成分享链接;draft/published/archived 版本可管理 |
| **E** | 主控意图路由(超级编排) | 一个输入框自动判断聊天/研究/交付,派发 glomi_forge 子 agent | A–D | 主对话识别交付意图,创建/复用 forge session,进度+产物回填对话 |

> A 与 INFRA 可并行起步:A 用本地 docker-compose Daytona 解锁开发,INFRA 同时推进国内 k8s 部署。B 依赖 INFRA 提供稳定生产底座。

---

## 各节点详述

### 节点 A —— glomi_forge 地基 + 落地页端到端
已完成子项目 A 代码落地。要点:新并行模块 + 新表 + feature flag;`SandboxProvider`/`BuilderAdapter` Protocol + `DaytonaSandboxProvider` + `PiBuilderAdapter` + `ForgeOrchestrator`;1 个 `glomi-landing-page` 模板;复用平台模型目录映射 Pi;最小前端 + 复用预览。
- **交付物**:领域模型、DB/session/event、编排状态机、sandbox launcher、Celery task、API/SSE、最小内测页、编排/adapter 单测和 gated Daytona/Pi E2E 均已落地。
- **当前边界**:真实 Daytona/Pi 端到端由 `DAYTONA_API_URL` / `DAYTONA_API_KEY` gate 控制；本地缺 Daytona control plane 和 snapshot 时测试安全 skip。生产可用仍依赖 INFRA 提供国内 Daytona、自有 snapshot、资源治理和模型兼容白名单。
- **关键经验**:后端通过自有 `ForgeEvent` JSONL 契约和 `SandboxProvider` / `BuilderAdapter` 协议隔离 Pi/Daytona 细节，后续替换 builder 或 sandbox 底座时不需要重写 session/event/API 层。

### 节点 INFRA —— Daytona 国内自托管
- **内容**:Daytona 全栈(api/runner/proxy/ssh-gateway/Postgres/Redis/Dex/Registry)Helm 部署到阿里云/腾讯云 k8s;镜像 registry 国内化;`glomi-*` snapshot 构建与推送流水线;网络白名单/出站最小化;GlomiAI → Daytona 的认证与 endpoint 配置。
- **退出标准**:生产 k8s 上 Daytona 稳定,A 的端到端能跑在国内底座上。
- **风险**:Daytona 自托管需较强 k8s 运维;on-prem k8s 路径相对新;最低 4 vCPU/16GB/200GB 资源成本;AGPL 合规(不改源、仅 API 调用)。

### 节点 B —— 生命周期 + 资源治理
- **内容**:`GlomiForgeStatus` 接 Daytona 生命周期(Started/Stopped/Archived/Ephemeral);auto-stop / auto-archive 策略;`SANDBOX_MAX_CONCURRENT_PER_ORG`、空闲超时、CPU/内存限额;失败恢复与重试;沙箱清理;可观测日志与指标。映射见 docs/glomi/forge/forge-arch.md §7.2。
- **退出标准**:用户隔天可恢复继续改;资源受控不拖垮底座;有失败恢复路径。

### 节点 C —— 模板扩展
- **内容**:`glomi-slides`(PptxGenJS/Marp)、`glomi-report`(Python + MD/HTML/PDF)、`glomi-dashboard`(Python + pandas + charting)。每模板绑定 snapshot + 默认目录结构 + AGENTS.md/SYSTEM.md + output contract + reviewer rules。Volume 设计(shared-assets / workspace-state / evidence-pack)在此落地。
- **退出标准**:3 个新模板端到端跑通;template system 抽象经多模板验证。

### 节点 D —— Reviewer + 发布/分享闭环
- **内容**:`Reviewer` 后台 agent(只校验 spec/acceptance/模块缺失/evidence 引用,不重执行,输出进 `/review` 回填 session);`OutputManifest` → 可公开/私密分享链接(对接 E6 Sparkpage 式分享页);版本化(draft/published/archived),preview 与 artifact 分离。
- **退出标准**:产物可自动验收 + 导出 + 生成分享链接 + 版本管理。

### 节点 E —— 主控意图路由(超级编排)
- **内容**:对接 GlomiAI.md E13。在主 chat(`chat/llm_loop.py`)识别交付意图,创建/复用 glomi_forge session,流式回填进度与产物;复用现成原语(CodingAgentTool/dr_loop/Emitter-Packet);双通道 canvas(Chat Stream + Canvas Stream);取消独立 Craft 心智。research 在主控侧整理 evidence pack 供 builder 消费。
- **退出标准**:用户从一个中文输入框开始,系统自动判断并在需要交付物时派发 glomi_forge,产物回填对话。

---

## 推进方式

1. **每个节点单独走** brainstorming spec → writing-plans 计划 → 实现 → 验收,本路线图只做节点编排,不替代各节点 spec。
2. **feature flag 贯穿**:`ENABLE_GLOMI_FORGE` 关闭时零行为变化,旧 Craft 保持可用,直到 E 完成再决定下线 opencode 路径。
3. **变更记录**:每个节点的落地、坑、学习写入 `summary.md`;产品层变化反映到 `docs/GlomiAI.md`。
4. **不要一次性重写主控**:E 是最后一步,前面先把 glomi_forge 在新底座上跑稳。

---

## 当前状态

- [x] 设计稿研读 + 代码库现状盘点 + 底座调研(Daytona 自托管可行/AGPL、Pi 自托管/RPC)
- [x] 节点 A spec 完成
- [x] 节点 A 实现计划(writing-plans)
- [x] 节点 A 实现
- [ ] INFRA / B / C / D / E 各自 spec
