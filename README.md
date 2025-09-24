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

**Onyx** is a feature-rich, self-hostable Chat UI that works with any LLM. Onyx is easy to deploy and can run in a completely airgapped environment.

Deploy Onyx with a single command (or see deployment section below for other options):
```
curl -fsSL https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose/install.sh > install.sh && chmod +x install.sh && ./install.sh
```



## Features
- **Agents:** Build custom AI Agents with unique instructions, knowledge and actions.
- **Web Search:** Supporting Google PSE, Exa, and Serper as well as an in-house scraper or Firecrawl.
- **RAG:**
- **Connectors**
- **Actions & MCP:**
- **Code Interpreter**
- **Image Generation**

Works with any LLM provider (like OpenAI, Anthropic, Gemini, AWS Bedrock, Azure OpenAI, etc.) and self-hosted LLMs (like Ollama, vLLM, etc.)

## Deployment
**To try it out for free and get started in seconds, check out [Onyx Cloud](https://cloud.onyx.app/signup)**.

Onyx can also be run locally (even on a laptop) or deployed on a virtual machine with a single
`docker compose` command. Checkout our [docs](https://docs.onyx.app/deployment/getting_started/quickstart) to learn more.

We also have built-in support for high-availability/scalable deployment on Kubernetes.
References [here](https://github.com/onyx-dot-app/onyx/tree/main/deployment).


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


## 🔌 Connectors
Keep knowledge and access up to sync across 40+ connectors:

- Google Drive
- Confluence
- Slack
- Gmail
- Salesforce
- Microsoft Sharepoint
- Github
- Jira
- Zendesk
- Gong
- Microsoft Teams
- Dropbox
- Local Files
- Websites
- And more ...

See the full list [here](https://docs.onyx.app/admin/connectors/overview).


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