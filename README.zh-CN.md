<a name="readme-top"></a>

<h2 align="center">
    <a href="https://www.onyx.app/?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme"> <img width="50%" src="https://github.com/onyx-dot-app/onyx/blob/logo/OnyxLogoCropped.jpg?raw=true" /></a>
</h2>

<p align="center">
    <a href="https://discord.gg/TDJ59cGV2X" target="_blank">
        <img src="https://img.shields.io/badge/discord-join-blue.svg?logo=discord&logoColor=white" alt="Discord" />
    </a>
    <a href="https://docs.onyx.app/?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme" target="_blank">
        <img src="https://img.shields.io/badge/docs-view-blue" alt="文档" />
    </a>
    <a href="https://www.onyx.app/?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme" target="_blank">
        <img src="https://img.shields.io/website?url=https://www.onyx.app&up_message=visit&up_color=blue" alt="网站" />
    </a>
    <a href="https://github.com/onyx-dot-app/onyx/blob/main/LICENSE" target="_blank">
        <img src="https://img.shields.io/static/v1?label=license&message=MIT&color=blue" alt="许可证" />
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

# Onyx - 由你的所有应用驱动的上下文层

> “大语言模型了解公开的信息，但如果它也能了解团队内部的情况呢？我想要的是一位 AI 同事，而不是一位刚入职的 AI 新人。”

**[Onyx](https://www.onyx.app/?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme)** 是面向团队和 AI 智能体的知识/上下文层。

Onyx 可连接 50 多种应用，为其中的知识建立索引并提供检索。同时，灵活的自托管部署让你掌控自己的数据。

除了知识检索，Onyx 还通过网页搜索、沙箱、技能等高级功能扩展大语言模型的能力。

> [!TIP]
> 使用一条命令部署：
> ```
> curl -fsSL https://onyx.app/install_onyx.sh | bash
> ```

![Onyx 聊天界面回答关于使用场景的问题](docs/assets/onyx-chat-use-cases.png)

---

## Onyx 的工作原理

Onyx 为所有已连接数据源中的知识建立统一表示。它获取数据及其元数据、权限等信息，并将其导入系统，供后续应用使用。

与基于 MCP 的搜索和不建立索引的方案相比，Onyx 能以更低的延迟和成本提供更可靠的上下文。无论是简单的关键词查询，还是复杂的研究任务，都可以使用这些上下文。

智能体无需协调数十个 MCP 服务并反复搜索，消耗成千上万个 token。Onyx 直接从内部知识表示中快速检索上下文，仅保留最相关的原始文档。

## ⭐ 功能特性

- **🔍 智能体 RAG：** 结合混合索引与专为信息检索优化的智能体框架，提供高质量的搜索与问答。
- **🔬 深度研究：** 通过多步骤研究流程生成深入的报告。
- **🤖 自定义智能体：** 构建具有专属知识范围、自定义指令和操作能力的 AI 智能体。
- **🌍 网页搜索：** 通过实时网页搜索补充内部知识。
  - 支持 Serper、Google PSE、Brave、SearXNG 等。
  - 内置网页爬虫，并支持 Firecrawl/Exa。
- **▶️ 外部操作与 MCP：** 让 Onyx 智能体在外部应用中执行操作，完成完整的任务流程。
- **💻 安全沙箱：** 在沙箱中执行代码并处理过程文件，支持复杂的工作流程。
- **📄 内容生成：** 生成文档、图表及其他可下载的文件。
- **🎙️ 语音模式：** 通过文字转语音和语音转文字与 Onyx 交互。

Onyx 支持所有主流 LLM 提供商，包括自托管方案（如 Ollama、LiteLLM、vLLM 等）和专有服务（如 Anthropic、OpenAI、Gemini 等）。

更多内容请参阅我们的[文档](https://docs.onyx.app/welcome?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme)！

---

## 安全与数据处理

![Onyx 架构：所有组件均在你的环境中运行](docs/assets/architecture.png)

连接组织知识时，必须防止敏感的知识产权信息泄露给组织内外未经授权的人员。

Onyx 支持可与外部网络隔离的自托管部署。文档索引、数据库和数据处理均在一组独立完整的服务中运行。

你还可以选择可信的嵌入模型和 LLM 提供商，两者均可在本地运行。

---

## 随时随地访问 Onyx

无论问题来自哪个入口，Onyx 都使用相同的安全机制和细粒度权限控制。

- **网页和桌面应用** - 提出问题、与 Onyx AI 智能体交互，并使用上述全部功能。
- **Slack 和 Discord 机器人** - 通过连接组织知识的机器人，直接在 Slack 或 Discord 中获取答案。
- **MCP 服务器** - 将 Claude Code、Open Code、Codex 或任何 MCP 客户端连接到 Onyx。AI 智能体可以获取公司上下文，并遵循与使用者相同的访问权限。
- **Chrome 扩展** - 直接在 Chrome 的任意标签页中查询 Onyx，并使用当前页面的上下文。
- **可嵌入组件** - 轻松将 Onyx 功能添加到你的应用或网站中。

---

## 🚀 部署模式

> Onyx 支持 Docker、Kubernetes、Helm/Terraform 部署，并为主流云提供商提供指南。
> 详细部署指南见[这里](https://docs.onyx.app/deployment/overview)。

Onyx 提供两种部署模式：Standard（标准版）和 Lite（轻量版）。

#### Standard Onyx

提供 Onyx 的完整功能，推荐有正式使用需求的用户和较大规模的团队使用。相比 Lite 模式，还包含以下组件：

- 用于 RAG 的向量与关键词索引。
- 后台容器，用于运行任务队列和工作进程，从连接器同步知识。
- AI 模型推理服务器，用于运行索引和推理所需的深度学习模型。
- 通过内存缓存（Redis）和对象存储（MinIO）优化大规模使用时的性能。

#### Onyx Lite

Lite 模式是轻量级的 AI 聊天界面。它占用的资源更少（内存低于 1GB），技术栈更简单，但无法为文档建立索引。
适合希望快速试用 Onyx 界面的用户，或仅需要聊天界面和智能体功能的团队。

> [!TIP]
> **如需免费试用 Onyx 且无需部署，请访问 [Onyx Cloud](https://cloud.onyx.app/signup?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme)。**

---

## 🏢 面向企业的 Onyx

Onyx 适合各种规模的团队，从个人用户到大型跨国企业：

- 👥 协作：与组织中的其他成员共享对话和智能体。
- 🔐 单点登录：通过 Google OAuth、OIDC 或 SAML 实现 SSO。通过 SCIM 同步用户组并管理用户账户。
- 🛡️ 基于角色的访问控制：通过 RBAC 控制对智能体、操作等敏感资源的访问。
- 📊 分析：按团队、LLM 或智能体查看使用情况图表。
- 🕵️ 查询历史：审计使用情况，确保组织安全使用 AI。
- 💻 自定义代码：运行自定义代码，移除个人身份信息（PII）、拒绝敏感查询或执行自定义分析。
- 🎨 品牌定制：自定义名称、图标、横幅等，调整 Onyx 的外观。

## 📚 许可证

Onyx 提供两个版本：

- Onyx 社区版（CE）采用 MIT 许可证，可免费使用，涵盖 RAG、AI 聊天、智能体和操作的全部核心功能。
- Onyx 企业版（EE）提供主要面向大型组织的额外功能。

功能详情请参阅[官网](https://www.onyx.app/pricing?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme)。

## 👪 社区

欢迎在 **[Discord](https://discord.gg/TDJ59cGV2X)** 加入我们的开源社区！

## 💡 贡献

希望参与贡献？请参阅[贡献指南](CONTRIBUTING.md)。
