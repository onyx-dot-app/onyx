<a name="readme-top"></a>

<h2 align="center">
    <a href="https://www.onyx.app/"> <img width="50%" src="https://github.com/onyx-dot-app/onyx/blob/logo/OnyxLogoCropped.jpg?raw=true)" /></a>
</h2>

<p align="center">Open Source AI Platform</p>

<p align="center">
    <a href="https://discord.gg/TDJ59cGV2X" target="_blank">
        <img src="https://img.shields.io/badge/discord-join-blue.svg?logo=discord&logoColor=white" alt="Discord">
    </a>
    <a href="https://docs.onyx.app/" target="_blank">
        <img src="https://img.shields.io/badge/docs-view-blue" alt="Documentation">
    </a>
    <a href="https://docs.onyx.app/" target="_blank">
        <img src="https://img.shields.io/website?url=https://www.onyx.app&up_message=visit&up_color=blue" alt="Documentation">
    </a>
    <a href="https://github.com/onyx-dot-app/onyx/blob/main/LICENSE" target="_blank">
        <img src="https://img.shields.io/static/v1?label=license&message=MIT&color=blue" alt="License">
    </a>
</p>



**[Onyx](https://www.onyx.app/)** is a feature-rich, self-hostable Chat UI that works with any LLM. It is easy to deploy and can run in a completely airgapped environment.

Onyx comes loaded with advanced features like Agents, Web Search, RAG, MCP, Deep Research, Connectors to 40+ knowledge sources, and more.

> [!TIP]
> Run Onyx with one command (or see deployment section below):
> ```
> curl -fsSL https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose/install.sh > install.sh && chmod +x install.sh && ./install.sh
> ```

****

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

Onyx works with all LLMs (like OpenAI, Anthropic, Gemini, etc.) and self-hosted LLMs (like Ollama, vLLM, etc.)

To learn more about the features, check out our [documentation](https://docs.onyx.app/welcome)!



## 🚀 Deployment
Onyx supports deployments in Docker, Kubernetes, Terraform, along with guides for major cloud providers.

See guides below:
- [Docker](https://docs.onyx.app/deployment/local/docker) or [Quickstart](https://docs.onyx.app/deployment/getting_started/quickstart) (best for most users)
- [Kubernetes](https://docs.onyx.app/deployment/local/kubernetes) (best for large teams)
- [Terraform](https://docs.onyx.app/deployment/local/terraform) (best for teams already using Terraform)
- Cloud specific guides (best if specifically using [AWS EKS](https://docs.onyx.app/deployment/cloud/aws/eks), [Azure VMs](https://docs.onyx.app/deployment/cloud/azure), etc.)

> [!TIP]  
> **To try Onyx for free without deploying, check out [Onyx Cloud](https://cloud.onyx.app/signup)**.



## 🔍 Other Notable Benefits
Onyx is built for teams of all sizes, from individual users to the largest global enterprises.

- **Enterprise Search**: far more than simple RAG, Onyx has custom indexing and retrieval that remains performant and accurate for scales of up to tens of millions of documents.
- **Security**: SSO (OIDC/SAML/OAuth2), RBAC, encryption of credentials, etc.
- **Management UI**: different user roles such as basic, curator, and admin.
- **Document Permissioning**: mirrors user access from external apps for RAG use cases.



## 🚧 Roadmap
To see ongoing and upcoming projects, check out our [roadmap](https://github.com/orgs/onyx-dot-app/projects/2)!



## 📚 Licensing
There are two editions of Onyx:

- Onyx Community Edition (CE) is available freely under the MIT license.
- Onyx Enterprise Edition (EE) includes extra features that are primarily useful for larger organizations.
For feature details, check out [our website](https://www.onyx.app/pricing).



## 👪 Community
Join our open source community on **[Discord](https://discord.gg/TDJ59cGV2X)**!



## 💡 Contributing
Looking to contribute? Please check out the [Contribution Guide](CONTRIBUTING.md) for more details.
