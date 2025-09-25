<a name="readme-top"></a>

<h2 align="center">
<a href="https://www.onyx.app/"> <img width="50%" src="https://github.com/onyx-dot-app/onyx/blob/logo/OnyxLogoCropped.jpg?raw=true)" /></a>
</h2>

<p align="center">
<p align="center">Open Source AI Platform</p>

<p align="center">
<a href="https://docs.onyx.app/" target="_blank">
    <img src="https://img.shields.io/badge/docs-view-blue" alt="Documentation">
</a>
<a href="https://join.slack.com/t/onyx-dot-app/shared_invite/zt-34lu4m7xg-TsKGO6h8PDvR5W27zTdyhA" target="_blank">
    <img src="https://img.shields.io/badge/slack-join-blue.svg?logo=slack" alt="Slack">
</a>
<a href="https://discord.gg/TDJ59cGV2X" target="_blank">
    <img src="https://img.shields.io/badge/discord-join-blue.svg?logo=discord&logoColor=white" alt="Discord">
</a>
<a href="https://github.com/onyx-dot-app/onyx/blob/main/README.md" target="_blank">
    <img src="https://img.shields.io/static/v1?label=license&message=MIT&color=blue" alt="License">
</a>
</p>



**[Onyx](https://www.onyx.app/)** is a feature-rich, self-hostable Chat UI that works with any LLM. It is easy to deploy and can run in a completely airgapped environment.

> Onyx comes loaded with advanced features like AI Agents, RAG, Connectors to 40+ knowledge sources, Web Search, MCP, Deep Research, and more.

Deploy Onyx with a single command (or see deployment section below):
```
curl -fsSL https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose/install.sh > install.sh && chmod +x install.sh && ./install.sh
```

![Onyx Chat Silent Demo](https://github.com/onyx-dot-app/onyx/releases/download/v0.21.1/OnyxChatSilentDemo.gif)

## ⭐ Features
- **🤖 Custom Agents:** Build AI Agents with unique instructions, knowledge and actions.
- **🌍 Web Search:** Browse the web with Google PSE, Exa, and Serper as well as an in-house scraper or Firecrawl.
- **🔍 RAG:** Best in class hybrid-search + knowledge graph for uploaded files and ingested documents from connectors. 
- **🔌 Connectors:** Pull knowledge, metadata, and access information from over 40 applications.
- **▶️ Actions & MCP:** Give AI Agents the ability to interact with external systems.
- **💻 Code Interpreter:** Execute code to analyze data, render graphs and create files.
- **🎨 Image Generation:** Generate images based on user prompts.
- **👥 Collaboration Features:** Chat sharing, user management, usage analytics, and more.

Onyx works with any LLM provider (like OpenAI, Anthropic, Gemini, etc.) and self-hosted LLMs (like Ollama, vLLM, etc.)

To learn more about Onyx's features, check out our [documentation](https://docs.onyx.app/welcome)!



## 🚀 Deployment
Onyx supports deployments in Docker, Kubernetes, Terraform, along with guides for major cloud providers.

See guides below:
- [Docker](https://docs.onyx.app/deployment/local/docker) or [Quickstart](https://docs.onyx.app/deployment/getting_started/quickstart) (best for most users)
- [Kubernetes](https://docs.onyx.app/deployment/local/kubernetes) (best for large teams)
- [Terraform](https://docs.onyx.app/deployment/local/terraform) (best for teams already using Terraform)
- Cloud specific guides (best if specifically using [AWS EKS](https://docs.onyx.app/deployment/cloud/aws/eks), [Azure VMs](https://docs.onyx.app/deployment/cloud/azure), etc.)

> [!TIP]  
> **To try it out for free without a deployment, check out [Onyx Cloud](https://cloud.onyx.app/signup)**.


## 🔍 Other Notable Benefits of Onyx
- Custom deep learning models for indexing and inference time, only through Onyx + learning from user feedback.
- Flexible security features like SSO (OIDC/SAML/OAuth2), RBAC, encryption of credentials, etc.
- Knowledge curation features like document-sets, query history, usage analytics, etc.
- Scalable deployment options tested up to many tens of thousands users and hundreds of millions of documents.


## 🚧 Roadmap
- New methods in information retrieval (StructRAG, LightGraphRAG, etc.)
- Personalized Search
- Organizational understanding and ability to locate and suggest experts from your team.
- Code Search
- SQL and Structured Query Language


## 📚 Licensing
There are two editions of Onyx:

- Onyx Community Edition (CE) is available freely under the MIT Expat license. Simply follow the Deployment guide above.
- Onyx Enterprise Edition (EE) includes extra features that are primarily useful for larger organizations.
For feature details, check out [our website](https://www.onyx.app/pricing).

To try the Onyx Enterprise Edition:
1. Checkout [Onyx Cloud](https://cloud.onyx.app/signup).
2. For self-hosting the Enterprise Edition, contact us at [founders@onyx.app](mailto:founders@onyx.app) or book a call with us on our [Cal](https://cal.com/team/onyx/founders).


## 💡 Contributing
Looking to contribute? Please check out the [Contribution Guide](CONTRIBUTING.md) for more details.