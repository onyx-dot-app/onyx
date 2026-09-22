<a name="readme-top"></a>

<h2 align="center">
    <a href="https://www.onyx.app/?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme"> <img width="50%" src="https://github.com/onyx-dot-app/onyx/blob/logo/OnyxLogoCropped.jpg?raw=true" /></a>
</h2>

<p align="center">
    <a href="https://discord.gg/TDJ59cGV2X" target="_blank">
        <img src="https://img.shields.io/badge/discord-join-blue.svg?logo=discord&logoColor=white" alt="Discord" />
    </a>
    <a href="https://docs.onyx.app/?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme" target="_blank">
        <img src="https://img.shields.io/badge/docs-view-blue" alt="Documentation" />
    </a>
    <a href="https://www.onyx.app/?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme" target="_blank">
        <img src="https://img.shields.io/website?url=https://www.onyx.app&up_message=visit&up_color=blue" alt="Website" />
    </a>
    <a href="https://github.com/onyx-dot-app/onyx/blob/main/LICENSE" target="_blank">
        <img src="https://img.shields.io/static/v1?label=license&message=MIT&color=blue" alt="License" />
    </a>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/12516" target="_blank">
    <img src="https://trendshift.io/api/badge/repositories/12516" alt="onyx-dot-app/onyx | Trendshift" style="width: 250px; height: 55px;" />
  </a>
</p>

<p align="center">
  <a href="./README.md">English</a> | <b>简体中文</b>
</p>

# Onyx

**[Onyx](https://www.onyx.app/?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme)** 是为你的员工和 Agent 提供完整上下文的 AI 平台。

> [!TIP]
> 一条命令即可部署：
>
> ```
> curl -fsSL https://onyx.app/install_onyx.sh | bash
> ```

![Onyx Chat Silent Demo](https://github.com/onyx-dot-app/onyx/releases/download/v3.0.0/Onyx.gif)

---

## Onyx 是什么？

Onyx 开源，并运行在你自己的环境中。你接入 Slack、Google Drive、Confluence、Jira、GitHub、Salesforce 以及 50+ 其他来源，Onyx 把它们持续索引到一个关键词 + 向量的混合索引中，从而带引用地回答问题。你可以通过聊天界面、Slack、Chrome 扩展来使用它，也可以把它作为 MCP 服务器，为你自己的 Agent 提供上下文。

它比逐个应用实时搜索效果更好，原因在于索引在你提问之前就已经存在。一次检索取代了跨应用的一连串实时搜索，这意味着更少的往返、每个答案更少的 token，以及来自那些没人想到去查的来源的结果。

开箱即有的功能：

- **Agentic RAG。** 在混合索引之上做查询改写和路由。在我们的开源基准 [EnterpriseRAG-Bench](https://www.onyx.app/enterpriserag-bench?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme)（500 个问题）上，Onyx 优于 Azure AI Search、OpenAI File Search 和 Vertex AI Search。
- **深度研究。** 多步研究，生成带引用的长篇报告。截至 2026 年 2 月位居[排行榜](https://github.com/onyx-dot-app/onyx_deep_research_bench)榜首。
- **自定义 Agent。** 每个 Agent 拥有专属的指令、知识和 Action。
- **Action 与 MCP。** Agent 可以调用外部 API 和 MCP 服务器。
- **Web 搜索。** 搜索支持 Serper、Google PSE、Brave、SearXNG、Exa 和 Tavily，网页抓取支持内置爬虫、Firecrawl 或 Tavily Extract。
- **代码执行。** 用于数据分析、绘图和文件编辑的沙箱。
- **Artifact、语音模式和图像生成。**

---

## 为什么要自托管

每一款托管的企业 AI 产品都希望把你的文档和提示词放进它的云里，这意味着你要接受它的数据保留策略、它的访问控制和它的训练条款。Onyx 则运行在你的环境中，这些问题都不存在。

```mermaid
flowchart LR
    subgraph boundary["你的环境（VPC、数据中心或物理隔离网络）"]
        direction LR
        subgraph sources["你的知识来源"]
            S1[Slack]
            S2[Google Drive]
            S3[Confluence]
            S4[50+ 其他来源]
        end
        subgraph onyx["Onyx"]
            W[Web + API 服务]
            C[同步 Worker]
            IDX[(混合索引<br/>OpenSearch)]
            DB[(Postgres)]
            EMB[Embedding + 重排序<br/>推理服务]
        end
        LLMself[自托管 LLM<br/>Ollama、vLLM、开源权重]
        U[用户：Web、桌面、Slack、Chrome]
        A[Agent：MCP 客户端]
    end
    LLMapi[托管 LLM API<br/>可选]

    sources -->|"文档 + 权限"| C
    C --> EMB --> IDX
    C --> DB
    U --> W
    A --> W
    W --> IDX
    W --> DB
    W --> LLMself
    W -.->|"仅在你选择时"| LLMapi
```

- **一切都留在你的边界之内。** 索引、数据库、embedding 模型和模型流量全部运行在你控制的机器上，无论那是你的云账户、你的数据中心，还是一个物理隔离的网络。
- **没有内容外发。** Onyx 自身唯一的外发请求是用量遥测：一个安装 UUID、版本、事件类型、耗时，以及企业版部署中实例的邮箱域名。其中绝不包含文档或提示词，设置 `DISABLE_TELEMETRY=true` 即可关闭。Sentry 和 PostHog 默认关闭，除非你配置了对应的密钥。
- **任意模型。** 通过 Ollama、vLLM 或 LiteLLM 在自己的 GPU 上运行开源权重，或用你自己的密钥接入 Anthropic、OpenAI、Gemini 等。Onyx 绝不会把提示词经由第三方代理，你可以一键切换供应商，或限制每个用户组可以使用哪些供应商。
- **开源。** 社区版采用 MIT 许可证，代码就在本仓库中，所以你的安全团队可以阅读所有接触你数据的代码，自行构建镜像，并确认没有隐藏的外发流量。
- **权限同步（企业版）。** Onyx 从 Google Drive、Confluence、Jira、GitHub、Slack、SharePoint、Gmail、Outlook、Teams、Zoom、Box 和 Canvas 同步文档级 ACL，并在查询时对 Salesforce 结果实时过滤。无论是人还是 Agent 发起的每一次查询，都只会返回该用户在来源系统中本来就能打开的文档。同步默认每 5 到 30 分钟运行一次。
- **审计（企业版）。** 查询历史记录谁问了什么以及引用了哪些文档，[审计日志](docs/AUDIT_LOGGING.md)以 SIEM 可摄取的格式记录登录、管理员变更和访问控制变更。

---

## 在任何地方使用

无论问题从哪里发出，用的都是同一套索引和同一套权限。

- **Web 和桌面应用（macOS）。** 聊天、深度研究、Agent，以及上面功能列表中的一切。
- **Slackbot。** 答案直接出现在大家本来就在提问的频道里。
- **MCP 服务器。** 把 Claude Code、Cursor、Codex 或任何 MCP 客户端指向 Onyx，你的 Agent 就能获得企业上下文，且访问控制与运行它的人完全一致。
- **Chrome 扩展。** 在任意标签页中查询 Onyx。

完整的 Connector 列表见[此处](https://www.onyx.app/connectors?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme)，文档见[此处](https://docs.onyx.app/welcome?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme)。

---

## 部署

下面每种方式运行的都是同一组镜像，区别只在于你想自己运维多少。完整指南见 [docs.onyx.app/deployment](https://docs.onyx.app/deployment/overview)。

- **引导式安装（Docker Compose）。** 页面顶部的一行命令会安装 `onyx-cli` 并运行 `onyx-cli deploy install`，它把 compose 文件写入 `~/.config/onyx`，启动整套服务，之后的 `upgrade`、`stop`、`logs` 和 `uninstall` 也由它负责。加上 `--lite` 即可部署 Onyx Lite。单机部署选这个。
- **手动 Docker Compose。** 克隆仓库，把 `deployment/docker_compose/env.template` 复制为 `.env`，在该目录下运行 `docker compose up -d`。Lite 模式加 `-f docker-compose.onyx-lite.yml`，需要 nginx 加 Let's Encrypt TLS 则用 `docker-compose.prod.yml`。
- **Kubernetes（Helm）。** `helm repo add onyx https://onyx-dot-app.github.io/onyx`，然后 `helm install onyx onyx/onyx`。Chart 也以 OCI 制品的形式发布在 `ghcr.io/onyx-dot-app/charts/onyx`。多节点或自动扩缩的部署用这个。
- **Terraform。** `deployment/terraform/modules` 下有 AWS 和 Azure 的模块，另有一个用于 AWS ECS Fargate 的 CloudFormation 模板。

### Standard 与 Lite

**Standard** 是完整平台，也是 compose 文件默认启动的模式。它在 nginx 后面运行 API 服务和 Next.js Web 服务，一个负责 Connector 同步和权限同步的 Celery 后台 Worker，用于关键词 + 向量混合索引的 OpenSearch，两个模型服务（一个做索引时的 embedding，一个做查询时的 embedding 和重排序），以及 Postgres、用于缓存和认证状态的 Redis 和用于文件存储的 MinIO。凡是涉及 Connector 或 RAG 的场景都需要它。

**Lite** 是同样的 API 服务和 Web UI，但只依赖 Postgres。该 overlay 把 OpenSearch、Redis、MinIO、两个模型服务和后台 Worker 移入 Compose profile，使它们默认不启动，并把缓存、认证和文件存储都指向 Postgres。这个模式下 Connector 和 RAG 搜索是关闭的。与任意 LLM 聊天、工具、自定义 Agent、项目、用户文件上传和代码执行仍然可用，整套服务内存占用不到 1GB。需要时可以用 `--profile opensearch`、`--profile redis` 等把单个服务加回来。

> [!TIP]
> **想不部署直接体验 Onyx，请注册 [Onyx Cloud](https://cloud.onyx.app/auth/signup?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme)**。

---

## 许可证

**社区版（CE）** 采用 MIT 许可证，涵盖聊天、RAG、Agent 和 Action。**企业版（EE）** 增加 SSO（Google OAuth、OIDC、SAML 和 SCIM 用户开通）、RBAC、权限同步、自定义代码钩子、分析和查询历史、白标，以及 SOC 2 Type II。详情见[定价页面](https://www.onyx.app/pricing?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme)。

## 社区

加入我们的 **[Discord](https://discord.gg/TDJ59cGV2X)**。

## 贡献

请查看[贡献指南](CONTRIBUTING.md)。
