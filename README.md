<a name="readme-top"></a>

<h1 align="center">
    <img width="128" src="web/public/logo.svg" alt="InsightAI" />
    <br/>
    InsightAI
</h1>

<p align="center">AI-Powered Insight Platform</p>

<p align="center">
    <a href="https://github.com/KoloqAI/InsightAI" target="_blank">
        <img src="https://img.shields.io/badge/repo-KoloqAI%2FInsightAI-blue" alt="Repository" />
    </a>
    <a href="https://github.com/onyx-dot-app/onyx" target="_blank">
        <img src="https://img.shields.io/badge/upstream-onyx--dot--app%2Fonyx-black" alt="Upstream Onyx" />
    </a>
    <a href="https://github.com/KoloqAI/InsightAI/blob/main/LICENSE" target="_blank">
        <img src="https://img.shields.io/static/v1?label=license&message=MIT&color=blue" alt="License" />
    </a>
</p>

> ### Fork notice
>
> **InsightAI** is a rebranded fork of [Onyx](https://github.com/onyx-dot-app/onyx)
> (formerly Danswer). All core features, connectors, and documentation from the
> upstream project apply here unchanged.
>
> The rebrand is intentionally shallow and upstream-safe: internal package names,
> Docker image names, module paths, and infrastructure identifiers still use
> `onyx`. Only user-visible strings and brand assets have been customized.
> This keeps `git merge upstream/main` low-conflict — see
> [project_documentation.md](project_documentation.md) for the upstream sync
> workflow and the list of branding-patched files.

---

**InsightAI** is a feature-rich, self-hostable AI platform that works with any LLM. It is easy to deploy and can run in a completely airgapped environment.

InsightAI comes loaded with advanced features like Agents, Web Search, RAG, MCP, Deep Research, Connectors to 40+ knowledge sources, and more.

> [!TIP]
> Most operational documentation still lives at the upstream project's docs
> site: <https://docs.onyx.app>. Substitute "InsightAI" anywhere you see "Onyx"
> in user-facing copy.

---

![Onyx Chat Silent Demo](https://github.com/onyx-dot-app/onyx/releases/download/v0.21.1/OnyxChatSilentDemo.gif)



## ⭐ Features
- **🤖 Custom Agents:** Build AI Agents with unique instructions, knowledge and actions.
- **🌍 Web Search:** Browse the web with Google PSE, Exa, and Serper as well as an in-house scraper or Firecrawl.
- **🔍 RAG:** Best in class hybrid-search + knowledge graph for uploaded files and ingested documents from connectors. 
- **🔄 Connectors:** Pull knowledge, metadata, and access information from over 40 applications.
- **🔬 Deep Research:** Get in depth answers with an agentic multi-step search.
- **▶️ Actions & MCP:** Give AI Agents the ability to interact with external systems.
- **💻 Code Interpreter:** Execute code to analyze data, render graphs and create files.
- **🎨 Image Generation:** Generate images based on user prompts.
- **👥 Collaboration:** Chat sharing, feedback gathering, user management, usage analytics, and more.

InsightAI works with all LLMs (like OpenAI, Anthropic, Gemini, etc.) and self-hosted LLMs (like Ollama, vLLM, etc.)

To learn more about the features, check out the upstream [Onyx documentation](https://docs.onyx.app/welcome).



## 🚀 Deployment
InsightAI supports deployments in Docker, Kubernetes, Terraform, along with guides for major cloud providers.

See guides below:
- [Docker](https://docs.onyx.app/deployment/local/docker?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme) or [Quickstart](https://docs.onyx.app/deployment/getting_started/quickstart?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme) (best for most users)
- [Kubernetes](https://docs.onyx.app/deployment/local/kubernetes?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme) (best for large teams)
- [Terraform](https://docs.onyx.app/deployment/local/terraform?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme) (best for teams already using Terraform)
- Cloud specific guides (best if specifically using [AWS EKS](https://docs.onyx.app/deployment/cloud/aws/eks?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme), [Azure VMs](https://docs.onyx.app/deployment/cloud/azure?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme), etc.)



## 🔍 Other Notable Benefits
InsightAI is built for teams of all sizes, from individual users to the largest global enterprises.

- **Enterprise Search**: far more than simple RAG, InsightAI has custom indexing and retrieval that remains performant and accurate for scales of up to tens of millions of documents.
- **Security**: SSO (OIDC/SAML/OAuth2), RBAC, encryption of credentials, etc.
- **Management UI**: different user roles such as basic, curator, and admin.
- **Document Permissioning**: mirrors user access from external apps for RAG use cases.



## 🔄 Upstream sync

This fork pulls changes from [`onyx-dot-app/onyx`](https://github.com/onyx-dot-app/onyx) on a regular cadence. To sync:

```bash
scripts/sync_upstream.sh          # fetch and merge upstream/main
```

Only a small set of files carry InsightAI brand patches; see the "Branding patches" section in [project_documentation.md](project_documentation.md) for the full list. Any merge conflict should be confined to those files and is mechanical to resolve.



## 📚 Licensing
This fork preserves the upstream Onyx licensing model:

- The Community Edition (CE) is available freely under the MIT license.
- The Enterprise Edition (EE) code under `backend/ee/` and related paths remains subject to the upstream Onyx Enterprise License.

See [LICENSE](LICENSE) and [backend/ee/LICENSE](backend/ee/LICENSE).



## 💡 Contributing
Bugs and fixes that are generally applicable should be contributed upstream to [`onyx-dot-app/onyx`](https://github.com/onyx-dot-app/onyx) where appropriate. InsightAI-specific changes (branding, packaging) stay in this fork.
