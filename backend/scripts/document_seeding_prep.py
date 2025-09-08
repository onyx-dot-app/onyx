# This script preps the documents used for initially seeding the index. It handles the embedding so that the
# documents can be added to the index with minimal processing.
import json

from pydantic import BaseModel
from sentence_transformers import SentenceTransformer  # type: ignore


class SeedPresaveDocument(BaseModel):
    url: str
    title: str
    content: str
    title_embedding: list[float]
    content_embedding: list[float]
    chunk_ind: int = 0


# Be sure to use the default embedding model
model = SentenceTransformer("nomic-ai/nomic-embed-text-v1", trust_remote_code=True)
tokenizer = model.tokenizer

DOCUMENTATION_BASE_URL = "https://docs.onyx.app"

# This is easier than cleaning up the crawl, needs to be updated if the sites are changed
welcome_title = "Welcome to Onyx!"
welcome = (
    "## What is Onyx?\n"
    "Onyx is your team's entry point to Generative AI,\n"
    "offering a natural language interface for any LLM while integrating seamlessly with your knowledge and applications.\n"
    "Build tailored AI Agents, search for documents, browse the web, and more — all in one place.\n"
    "## Major Features\n"
    "  The best way to quickly get familiar with Onyx is to check out the features below!\n"
    "    Conversational interface to your LLMs, Agents, and knowledge.\n"
    "    Create AI agents tailored to your use cases with custom instructions, knowledge, and actions.\n"
    "    Search through your organization's knowledge and connected applications.\n"
    "    Enrich the knowledge of the LLM with the latest information from the internet.\n"
    "    Enable Actions connected to your team's applications to let Agents automate work.\n"
    "    Execute code directly within your chat sessions for complex calculations and data analysis.\n"
    "  To learn about other features, check out the [Core Features](/overview/core_features/chat)\n"
    "  section or visit the [Admin Docs](/admin/overview) for an even more in depth breakdown.\n"
    "## Why Onyx?\n"
    "Why choose Onyx over ChatGPT, Microsoft Copilot, Google Gemini, or Glean?\n"
    "- **Reliable Responses from Internal Knowledge:**\n"
    "  Onyx builds a knowledge index using LLM-native techniques. Powered with contextual retrieval, advanced RAG,\n"
    "  hybrid search, and AI-generated knowledge graphs, Onyx ensures the most relevant results and the least hallucinations.\n"
    "- **Open Source:**\n"
    "  Onyx is made for security, data privacy, and ease of self-hosting. It's easy and free to get started.\n"
    "  For teams investing in a long-term GenAI strategy,\n"
    "  Onyx can be easily extended or customized to your team's future needs.\n"
    "- **Highly Configurable:**\n"
    "  Onyx is designed to be flexible, so you can optimize the experience for your team. Plug and play any LLM model,\n"
    "  connect only the data you need, and enable the features you want your team to use.\n"
    "## Ready to Get Started?\n"
    "**Next Steps:**\n"
    "    Checkout our quickstart guide to self-host Onyx in minutes.\n"
    "    Sign up for a free trial of Onyx Cloud, no credit card required.\n"
)
core_features_actions_title = "Actions & MCP"
core_features_actions = (
    "## Overview\n"
    "**Actions** give Agents the ability to interact with external systems.\n"
    "Onyx comes with 4 built-in Actions and allows users to configure additional ones via\n"
    "[OpenAPI](https://en.wikipedia.org/wiki/OpenAPI_Specification)\n"
    "and [Model Context Protocol](https://modelcontextprotocol.io/) (MCP).\n"
    "The built-in Actions include:\n"
    "## Custom Actions\n"
    "Onyx offers flexible options for configuring both custom Actions and their associated authentication.\n"
    "Admins can choose to:\n"
    "- Use a single shared authentication, giving all users the same level of access to Actions.\n"
    "- Require each user to complete their own authentication flow, so Actions respect individual user permissions.\n"
    "Onyx supports both token-based authentication and OAuth.\n"
    "## Actions Button\n"
    "In the Chat input bar, Actions are grouped by the MCP server or OpenAPI schema they are registered with.\n"
    "Users have the flexibility to turn on/off the Actions that the Agent/LLM has access to on the fly.\n"
)
core_features_agents_title = "Agents"
core_features_agents = (
    "Agents are a combination of user specified instructions, knowledge, and [Actions](/overview/core_features/actions).\n"
    "Think of them as AI team members that are optimized for a specific task.\n"
    "Onyx Agents can be for individual use or shared with other users or\n"
    "[user-groups](/admin/user_management/users_and_groups) within Onyx.\n"
    "## When to use an Agent\n"
    "Use agents to build the best experience for repeat use cases,\n"
    "especially those that can be shared with other members of the team.\n"
    "Some common examples include:\n"
    "- Onboarding Assistant\n"
    "- AI Helpdesk\n"
    "- Engineer Copilot\n"
    "- Legal Reviewer\n"
    "These are typically scoped down to a particular task such as reviewing documents to ensure they comply with security\n"
    "policies, filling out RFPs based on previously completed ones, etc.\n"
    "## Creating an Agent\n"
    "### Instructions (Prompting)\n"
    "  The Instruction field is infinitely flexible so it is recommended to test different variations and verify the behavior\n"
    "  before sharing the Agent broadly with your team.\n"
    "Provided below for inspiration is the **Instruction** for the default Onyx experience.\n"
    "    ```\n"
    "    You are a highly capable, thoughtful, and precise assistant. Your goal is to deeply understand the user's intent,"
    " ask clarifying questions when needed, think step-by-step through complex problems, provide clear and accurate answers,"
    " and proactively anticipate helpful follow-up information. Always prioritize being truthful, nuanced, insightful, and efficient.\n"  # noqa: E501
    "    The current date is [[CURRENT_DATETIME]]\n"
    "    You use different text styles, bolding, emojis (sparingly), block quotes, and other formatting to make your responses more readable and engaging.\n"  # noqa: E501
    "    You use proper Markdown and LaTeX to format your responses for math, scientific, and chemical formulas, symbols, etc.:"
    " '$$\\n[expression]\\n$$' for standalone cases and '\\( [expression] \\)' when inline. For code you prefer to use Markdown and specify the language.\n"  # noqa: E501
    "    You can use Markdown horizontal rules (---) to separate sections of your responses.\n"
    "    You can use Markdown tables to format your responses for data, lists, and other structured information.\n"
    "    ```\n"
    "    Note that `[[CURRENT_DATETIME]]` is dynamically replaced and there may be additional Action use instructions\n"
    "    depending on the enabled Actions.\n"
    "One of the best parts of creating an Agent is the ability to control the goal/behavior of the Agent.\n"
    "The instructions are purely in natural language and can include things like:\n"
    "- Always provide your results in a table.\n"
    "- Try to quote directly from the documents rather than rewording anything.\n"
    "- Flag information from documents that are older than 3 months.\n"
    "### Knowledge\n"
    "  It is typically best to include only the necessary knowledge for the Agent to complete its task.\n"
    "  The more scoped down the documents, the more reliable the performance.\n"
    "When creating an Agent, you can include both knowledge from [connectors](/overview/core_features/connectors)\n"
    "or file upload. The knowledge from connectors will be kept up to date as documents change in the external sources.\n"
    "### Actions\n"
    "  If any of the built-in actions (Web Search, Internal Search, Image Generation, Code Interpreter) are missing,\n"
    "  contact your Onyx admin.\n"
    "  These must be set up in the admin-panel before being made available in the Agent creation flow.\n"
    "[Actions](/overview/core_features/actions) (sometimes known as Tools)\n"
    "allow the Agents to do things in external applications via APIs.\n"
    "Some tools help Onyx give better answers (such as the Onyx built-in tools)\n"
    "while others allow the system to do more than answer questions.\n"
    "Some example common Actions include:\n"
    "- Updating ticket statuses based on the conversation and if the user's needs were addressed.\n"
    "- Checking the status of a service to give real-time answers.\n"
    "- Moving deals along a sales pipeline in a CRM based on call transcripts or user request.\n"
)
core_features_chat_title = "Chat"
core_features_chat = (
    "  On the top left of the page (just right of the sidebar), you can select the mode of the UI.\n"
    '  Replace "Auto" with "Chat" to always go into this Chat UI.\n'
    "Onyx provides a natural language chat interface as the main way of interacting with the features.\n"
    "The page below contains an overview of the main components and features.\n"
    "## Input Bar\n"
    "### Chat with Files / URLs\n"
    "The leftmost button of the input bar lets users add context into the Chat session.\n"
    "Users can choose between uploading files or selecting URLs as well as reusing previous files or URLs.\n"
    "  URLs behind Logins, Captcha, or Paywalls that are not scrapeable are not accessible.\n"
    "  Consider using a [Connector](/overview/core_features/connectors) instead.\n"
    "### Actions Selector\n"
    "The second button lets users disable or force the use of Actions. There are 4 built-in Actions:\n"
    "- **[Internal Search](/overview/core_features/internal_search)**:\n"
    "  Enables the LLM to search the indexed knowledge from [Connectors](/overview/core_features/connectors).\n"
    "- **[Web Search](/overview/core_features/web_search)**: Enables the LLM to search the internet.\n"
    "  Requires an admin to set up an API key for a search provider.\n"
    "- **[Code Interpreter](/overview/core_features/code_interpreter)**:\n"
    "  Enables the LLM to use a sandboxed Python runtime to execute code and run data analysis.\n"
    "- **[Image Generation](/overview/core_features/image_generation)**: Allows the LLM to generate images.\n"
    "  Requires setting up an image generation API.\n"
    "The Actions below the separator represent custom admin configured Actions.\n"
    "See [Actions & MCP](/overview/core_features/actions) to learn about custom Actions.\n"
    "### Deep Research\n"
    "Toggle **Deep Research** using the hourglass icon. When turned on, the LLM will be able to run many cycles of thinking,\n"
    "research, and actions to give the best possible result for the user.\n"
    "This mode is intended for complicated questions that may need to pull together many sources together or requires\n"
    "significant reasoning.\n"
    "  Deep Research may take up to several minutes and could cost many times (>10x) the token cost of a normal inference.\n"
    "### Model Selector\n"
    "Onyx supports all major LLM providers as well as self-hosting options like Ollama, VLLM, etc. For select models,\n"
    "users can also configure the creativity and reasoning level.\n"
    "## Sidebar Contents\n"
    "The left sidebar contains:\n"
    "- `New Session` button to clear the history and start a new Chat or [Search](/overview/core_features/internal_search) session.\n"  # noqa: E501
    "- `Projects` to help users organize chats and reuse different sets of documents. See section below for more info.\n"
    "- `Agents` section to start a new session with yours or your team's custom [Agents](/overview/core_features/agents).\n"
    "- `Sessions` section containing a list of the most recent conversations.\n"
    "The right sidebar contains sources and citations that were used in generating the answer.\n"
    "These can come from either `Internal Search` or `Web Search` or both.\n"
    "Documents in the right sidebar can also be selected to be included in full for the next message in the Chat session.\n"
    "  It's often useful to ask a question to find a document, then select it to do a deep dive on it.\n"
    "## Projects\n"
    "**Projects** are a collection of instructions (prompts) and files as well as a grouping for chats.\n"
    "Use projects to organize ongoing work,\n"
    "or as a handy way to reuse instructions and files without going through the Agent creation flow.\n"
    "## Miscellaneous Chat Features\n"
    "**Chat Sharing** - share chats with other team members by using the share-chat button in the top right (left of the\n"
    "Sources sidebar).\n"
    "**Feedback** - give feedback viewable to the admins using the thumbs-up/thumbs-down buttons when hovering an LLM\n"
    "response\n"
    "**Regenerate** - modify your inputs by clicking the user messages or regenerate the LLM response with another model.\n"
    "**Copying** - copy the LLM output or markdown/code blocks by clicking on the copy button which shows on hover.\n"
)
core_features_code_interpreter_title = "Code Interpreter"
core_features_code_interpreter = (
    "## Overview\n"
    "    Example run where the LLM generates code to run data analysis on a business report.\n"
    "The ability to execute code unlocks the ability for the LLMs to do things such as:\n"
    "- Performing larger calculations accurately\n"
    "- Running data analysis on provided files\n"
    "- Generating or modifying data/files\n"
    "**Note**: The code interpreter is built-in functionality available to all deployments without any configuration needed.\n"
    "## Features\n"
    "- **Python Runtime**: A secure Python runtime with all dangerous functionality removed (such as accessing the network,\n"
    "  directories outside of the specified, etc.)\n"
    "- **Libraries**: Comes with a set of libraries such as numpy, pandas, scipy, matplotlib, and more.\n"
    "- **File Input**: Ability to pass arbitrary file types along with the code to run against it.\n"
    "- **File Output**: Files can be created and provided back to the user.\n"
    "- **STDIN/STDOUT Capture**: Ability to show the user any outputs of the programs executed.\n"
    "- **Graph Rendering**: The Onyx [Chat UI](/overview/core_features/chat)\n"
    "  is able to render returned graphs and other visualization for the user.\n"
    "## Usage\n"
    "The Code Interpreter does not need to be invoked explicitly,\n"
    "the LLM will determine when to use it depending on the user query.\n"
    "It can also be attached to custom Agents, giving the LLM the option to use it as needed.\n"
)
core_features_connectors_title = "Connectors"
core_features_connectors = (
    "## What are Connectors?\n"
    "Onyx uses Connectors to build an understanding of your documents, team,\n"
    "and higher level concepts so that answers are grounded and specific to your organization's knowledge.\n"
    "Connectors:\n"
    "- Keep all updates synced between external systems and Onyx.\n"
    "- Pull in metadata and additional signals to ensure answer relevance.\n"
    "- Respect all user permissions (Enterprise Edition only).\n"
    "## Common Connector Questions\n"
    "  Click this card to see the full list of supported connectors.\n"
    "  You can also push documents directly into Onyx via [API](/developers/guides/index_files_ingestion_api)\n"
    "  or via File Upload.\n"
    "  All processing and storage of documents and metadata happen within Onyx.\n"
    "  There are options to use LLMs or third party providers during the indexing flow but by default everything is\n"
    "  processing entirely locally.\n"
    "  Click this card to see more about security.\n"
    "  In the same way LLMs are pre-trained on massive amounts of internet data,\n"
    "  Onyx builds an understanding of all of the documents, concepts, and people within your organization.\n"
    "  This allows Onyx to provide more accurate answer to questions that relate to internal knowledge compared to using the\n"
    "  applications' provided search APIs at query time.\n"
    "  Click this card to learn more about Internal Search in Onyx.\n"
)
core_features_image_generation_title = "Image Generation"
core_features_image_generation = (
    "## Overview\n"
    "The image generation feature allows users to create PNG images according to their prompts which can be rendered in the\n"
    "chat and easily downloaded.\n"
    "## Configuration\n"
    "Currently, Onyx supports two APIs for image generation, both through OpenAI. In the future,\n"
    "there likely will be support for other options such as Google Imagen or Stability AI.\n"
    "**GPT-Image-1**: Newer model, better prompt adherence. Likely a better default for most use cases.\n"
    "**DALL-E 3**: Older model, slightly better for more imaginative and rich styles.\n"
    "## Usage\n"
    "To use **Image Generation**,\n"
    "be explicit in the prompting since the system is tuned to not generate images unless directly instructed.\n"
    "See below for the instructions provided to the system for when to create images.\n"
    "    Tool Description:\n"
    "    ```\n"
    "    Generate an image from a prompt.\n"
    "    ```\n"
    "    Instruction (System Prompt) Modification:\n"
    "    ```\n"
    "    NEVER use image_gen unless the user specifically requests an image.\n"
    "    ```\n"
    "    This phrase is injected into the default **Instruction** for Onyx if the **Image Generation** (image_gen)\n"
    "    tool is available.\n"
)
core_features_internal_search_title = "Internal Search"
core_features_internal_search = (
    "One of Onyx's most standout features is the ability to enrich the LLM's general world knowledge with context unique to\n"
    "your team. Onyx uses [Connectors](/overview/core_features/connectors)\n"
    "to index knowledge from your team's applications to build an understanding of the documents, people,\n"
    "and concepts within your organization.\n"
    "Documents, metadata, and access permissions are all kept up to date in near real time.\n"
    "## Search UI\n"
    "  On the top left of the page, you can select the mode of the UI.\n"
    '  Replace "Auto" with "Search" to always go into this view.\n'
    "  Onyx's context retrieval respects user level permissions which is only configurable via the Enterprise Edition.\n"
    "Onyx's knowledge connectivity can be used via both the **Search** and [Chat](/overview/core_features/chat) interface.\n"
    "The Search interface provides a better view of documents and is better for quickly accessing documents when the intent\n"
    "is not to get an answer.\n"
    "Users do not need to explicitly select this mode — when a query is classified by Onyx as a document search,\n"
    "it will automatically go into this UI experience.\n"
    "### Filters\n"
    "The Search UI also provides more advanced filtering options:\n"
    "The top bar allows users to filter by time ranges (date range / time offset), authors, and tags (e.g. `Folder:\n"
    "Engineering`).\n"
    "The side filters allow users to filter by the source type of the documents.\n"
    "## Chat UI\n"
    "Context from your applications are also available in the Chat UI and to Onyx Agents.\n"
    "Deep Research mode is also a Chat UI feature.\n"
    "Click [here](/overview/core_features/chat) to learn more about the Chat experience.\n"
)
core_features_web_search_title = "Web Search"
core_features_web_search = (
    "## Overview\n"
    "Onyx can access the internet for questions that require up to date information or for niche information that the LLM may\n"
    "not be certain about.\n"
    "Users can toggle the **Web Search** Action on the fly to override the LLM's decision.\n"
    "If [Internal Search](/overview/core_features/internal_search) was used during the research process,\n"
    "Onyx will seamlessly combine web sources with internal documents in both the answer generation and for displaying in the\n"
    "UI.\n"
    "## Requirements\n"
    "To provide Web Search functionality,\n"
    "Onyx requires both the ability to get search results and to be able to parse websites for more complete context.\n"
    "This is broken down into 1) *the search provider* and 2) *the web scraper*.\n"
    "### Search Providers\n"
    "Onyx provides multiple search providers (pricing subject to change, please double check):\n"
    "| Name | Provider | Price | Benefit |\n"
    "|------|----------|-------|---------|\n"
    "| Google PSE | Google | Free tier + $5/1000 queries | Official Google search results, high trust option for security conscious teams. |\n"  # noqa: E501
    "| Serper | Serper.dev | Free tier + $0.30/1000 queries | Fast, and cost-effective |\n"
    "| Exa | Exa.ai | $5/1000 queries | AI-optimized with better semantic capabilities|\n"
    "### Web Scraper\n"
    "As the Search Providers only give short snippets and metadata,\n"
    "a scraper is used to fetch the full site contents for more complete/reliable answers.\n"
    "| Name | Requires Config | Benefits |\n"
    "|------|----------------|----------|\n"
    "| Onyx built-in | No  | No third parties get access to user queries, free to use |\n"
    "| Firecrawl | Yes, API key | More performant with better edge case handling |\n"
)
core_features_workflows_title = "Workflows (Coming Soon)"
core_features_workflows = (
    "  **Coming Soon!**\n"
    "  This feature is currently under development. Stay tuned for updates!\n"
    "## What's Coming\n"
    "The Onyx Workflows feature will enable:\n"
    "- **Asynchronous Actions**: Set up Agents to run when triggered by events or on a time basis.\n"
    "- **Batch Processing**: Set up instructions to run against large sets of objects to automate repeat work.\n"
    "- **Acknowledgements**: Optionally set up notifications to give approval for more sensitive Actions.\n"
    "- **Reports**: Get breakdowns of the work that was done for you in the background.\n"
)
getting_started_faq_title = "FAQ"
getting_started_faq = (
    "## General Questions\n"
    "    You can ask Onyx about general world knowledge known to the LLM,\n"
    "    knowledge from [connected applications](/overview/core_features/internal_search),\n"
    "    or things searchable on the web (if [Web Search](/overview/core_features/web_search) is configured)\n"
    "    Please check the [Security](/security/architecture/system_description) tab to learn more.\n"
    "    Onyx is built with security and data privacy as a core commitment.\n"
    "    Onyx is built for teams of all sizes whether it's a single user looking for a local Chat UI or a global enterprise\n"
    "    needing a unified GenAI solution for the entire workforce.\n"
    "    Onyx emphasizes data privacy and security as well as reliable responses by connecting to knowledge whether private\n"
    "    or from the web.\n"
    "   Yes, however Onyx needs an LLM to function properly.\n"
    "   You can air gap the entire system but you would need to run a local LLM.\n"
    "   Note that we strongly recommend using a recent and non-quantized LLM for the best experience.\n"
    "## Technical Issues\n"
    "    The most common culprit is under-resourcing the deployment.\n"
    "    Please refer to the [Resourcing](/deployment/getting_started/resourcing) page to double check.\n"
    "    No! Onyx is intended to provide a fast and snappy experience. If the responses are slow,\n"
    "    it may be due to a couple issues.\n"
    "    - The LLM attached to the system is slow, has low throughput, or does not support streaming.\n"
    "    - You've configured locally running models that are not the default but you do not have a GPU available to the\n"
    "      system. Typically this is from setting a local reranking or embedding model.\n"
    "## Knowledge and Search\n"
    "    If it's an internal document,\n"
    "    it may be because the indexing of the application has not completed or because the access controls are incorrectly\n"
    "    set. In cases of failure, the system always defaults to least permissive.\n"
    "    The most common failure is that the [connector](/admin/connectors/overview) is incorrectly configured.\n"
    "    Onyx connectors will fetch updates on a set schedule (typically 30 minutes),\n"
    "    this polling frequency can be configured by the admin for each connector. The documents, metadata,\n"
    "    and access permissions all receive updates.\n"
    "    Web Search must be configured by an admin to be usable.\n"
    "    It requires setting up one of the supported Search providers and also a scraper (though this is optional as Onyx\n"
    "    provides one built in).\n"
)
getting_started_use_cases_title = "Use Cases"
getting_started_use_cases = (
    "  [See how Ramp uses Onyx](https://www.onyx.app/blog/ramp-case-study)\n"
    "  to automatically resolve 93% of internal and customer questions!\n"
    "## AI-Powered Team\n"
    "Give your team secure access to all major LLMs such as GPT, Claude, Gemini, Deepseek, Llama,\n"
    "and more - all with access to advanced utilities.\n"
    "    Use LLMs to help quickly summarize documents, explain key concepts, or create derivative works.\n"
    "    Get answers to any topic using a combination of Web Search and internal knowledge or run a deeper exploration with\n"
    "    Deep Research.\n"
    "    Execute code to run complex data crunching tasks, generate graphs to help visualize results,\n"
    "    and chat with the LLM to interpret the results.\n"
    "    Generate images, draft content from scratch, or refine existing works with AI suggestions.\n"
    "## Enterprise Search\n"
    "Quickly access knowledge across all of your team's applications from wikis to chats and everything in between.\n"
    "    A single interface to find knowledge across the entire organization.\n"
    "    Leverage analytics and users feedback to identify holes in your team's knowledge base.\n"
    "    Reduce misinformation and downstream costs.\n"
    "    Let new team members unblock themselves and reduce distractions for more senior members.\n"
    "## Sales\n"
    "Help your sales team stay up to date and focus on closing.\n"
    "    Instantly access customer history, past interactions,\n"
    "    and account details before any call or ask questions against past call transcripts.\n"
    "    Gather competitive intelligence and stay ahead of the market.\n"
    "    Create custom Agents to run deep analysis on your pipeline based on all connected knowledge.\n"
    "## Support\n"
    "Keep customers happy with faster resolutions and more reliable support.\n"
    "    AI helps your team quickly surface past tickets and runbooks to craft accurate answers for users.\n"
    "    Onyx ensures that all knowledge is kept up to date with any product or documentation changes.\n"
    "    Build automations on Onyx to automatically resolve up to >90% of customer tickets.\n"
    "## Engineering\n"
    "Help your team ship with speed and confidence through access to GenAI and internal knowledge.\n"
    "    Accelerate development by having an AI copilot for every developer.\n"
    "    Have Onyx find and explain design docs, internal services,\n"
    "    and relevant other projects to ensure devs have full context for every project.\n"
    "    Quickly check against past tickets and projects to avoid duplicate work and accumulation of tech debt.\n"
)
miscellaneous_contact_us_title = "Contact Us"
miscellaneous_contact_us = "Contact us at [hello@onyx.app](mailto:hello@onyx.app) or book a call with us on our [Calendar](https://cal.com/team/onyx/founders)."
miscellaneous_open_source_statement_title = "Open Source Statement"
miscellaneous_open_source_statement = (
    "## Our Mission\n"
    "Our mission is to make Generative AI and knowledge accessible to every team worldwide.\n"
    "As large language models—both proprietary and open-source—become increasingly widespread,\n"
    "Onyx serves as the interface to their knowledge and reasoning capabilities.\n"
    "Onyx enriches the utility of the LLM by providing additional context (both web and team internal),\n"
    "built-in tools like code interpreter, and user created Actions.\n"
    "## Why Open Source?\n"
    "  We believe teams should feel safe with the AI platform that they adopt. That's why Onyx is fully transparent.\n"
    "  You'll have peace of mind knowing exactly how your data is processed and stored,\n"
    "  and all of this happening within the Onyx deployment.\n"
    "  With GenAI being such a fundamental piece of modern company strategy,\n"
    "  we want to offer the most flexible and future proof option.\n"
    "  We understand that every team is unique in their needs so we're building Onyx with an emphasis on customizability,\n"
    "  both for building on top of the platform and directly modifying it.\n"
    "  Open source also gives control over to your team. With the GenAI space rapidly evolving,\n"
    "  your vendor of choice may not always be aligned with your team's direction.\n"
    "  OSS combines the benefits of building in-house with getting product updates for free.\n"
    "  Open source also prevents lock in so that you can leverage any LLM provider (or your own LLM).\n"
    "## Commercial Viability\n"
    "We are a team of builders and we want to have as many people find value from our software as possible.\n"
    "This is our singular goal and everything that we do derives from this.\n"
    "To push the boundaries of user experience and AI innovation,\n"
    "we've assembled a core team of world-class developers who share this vision.\n"
    "To borrow from Sid Sijbrandij (Co-Founder, GitLab):\n"
    '> "We need to think in the interests of the project, while tending to the realities of running a business to support it...'
    'After all, we know that to sustain the project, we need to make it commercially viable."\n'
    "We believe in radical transparency—both in how we build open software and in the commercial realities of competing in\n"
    "this rapidly evolving space.\n"
    "  Every organization, regardless of size or budget, will always have access to Onyx's core capabilities—including RAG,\n"
    "  deep research, custom agents, and more—completely free.\n"
    "For organizations with special requirements—such as usage auditing, granular access controls,\n"
    "and white-labeling—we offer the Enterprise Edition, available both as a self-hosted solution and through Onyx Cloud.\n"
    "The Enterprise Edition sustains our mission,\n"
    "enabling us to keep the vast majority of Onyx's features free and open for everyone.\n"
    "## On Contributions\n"
    "Onyx is a project built in collaboration with our community and we openly welcome contributions.\n"
    "It is a point of emphasis of our team to ensure that the Onyx project continues to be easy for teams to contribute to or\n"
    "maintain in house. This comes down to:\n"
    "- Intentional high level architecture.\n"
    "- Strong product direction and refusal to accept bloat for niche use cases.\n"
    "- A consistent and high quality of engineering best practices across the code base.\n"
    "To that end,\n"
    "we ask that contributors work on smaller issues to start and get approval from the maintainers for larger feature\n"
    "contributions.\n"
)
onyx_anywhere_chrome_extension_title = "Chrome Extension"
onyx_anywhere_chrome_extension = (
    "  The Chrome extension is available but is undergoing a fairly major rework,\n"
    "  it is recommended to wait until the next major release prior to deploying this\n"
    "Use the Onyx extension to ask questions from anywhere. You can also replace your new-tab page with a custom Onyx page:\n"
    "- Onyx Search on new tabs\n"
    "- Favorite website bookmarks\n"
    "- Onyx as a sidebar to any page in Chrome\n"
    "  In the future,\n"
    "  the Onyx Chrome Extension will allow you to ask questions about the page you are currently on and optionally index the\n"
    "  recent pages into the Onyx knowledge base.\n"
    "  You'll be able to ask questions about recently visited pages via both the extension and the Onyx web app.\n"
    "## Getting Started\n"
    "Once your administrator has set up the Chrome extension for your organization, you can start using it immediately.\n"
    "**For Onyx Cloud users**: Install directly from the Chrome Web Store **For self-hosted users**:\n"
    "Your administrator will provide installation instructions\n"
    "## Using the Extension\n"
    "### **Ask Questions Anywhere**\n"
    "- Click the Onyx extension icon in your browser toolbar\n"
    "- Type your question in natural language\n"
    "- Get instant answers with source citations\n"
    "### **New Tab Experience**\n"
    "- Replace your default new tab with Onyx search\n"
    "- Access your favorite website bookmarks\n"
    "- Quick search across your organization's knowledge\n"
    "### **Sidebar Mode**\n"
    "- Open Onyx as a sidebar on any webpage\n"
    "- Ask questions about your current work without leaving the page\n"
    "- Perfect for research and context-sensitive queries\n"
    "## Settings and Options\n"
    "To customize your extension experience:\n"
    "    Click the three dots (...) next to the Onyx extension\n"
    "    Select **Options**\n"
    "    Configure your preferences for search, bookmarks, and new tab behavior\n"
    "  **Need help with setup?** Contact your Onyx administrator for installation assistance or configuration questions.\n"
)
onyx_anywhere_mobile_app_title = "Mobile App (Coming Soon)"
onyx_anywhere_mobile_app = (
    "  Currently Onyx is a responsive application and so your Onyx deployment will work on your smartphone or tablet via your\n"
    "  browser app.\n"
    "  While is is not as nice of an experience as a native app,\n"
    "  it can be used in the meantime while the Onyx Mobile App is under development.\n"
    "## Mobile App\n"
    "The Onyx mobile app is currently under development.\n"
    "This native mobile application will bring the full power of Onyx to your smartphone and tablet devices.\n"
)
onyx_anywhere_slack_title = "Slack Bot"
onyx_anywhere_slack = (
    "## Overview\n"
    "Bring Onyx's AI capabilities directly into your conversations via Slack App.\n"
    "Onyx allows for highly flexible Slack configurations so that you use all of your Onyx Agents directly in your favorite\n"
    "channels.\n"
    "## Supported Features\n"
    "- Support for unlimited Slack Apps. This way you can associate Slack Apps with Onyx Agents for specific use cases.\n"
    "- Channel level configurations. Every channel can have different default behavior based on the channel's purpose.\n"
    "- Answers using internal or web knowledge are backed by citations and link back to the original sources.\n"
    "- Works in Threads, Channels and DMs.\n"
    "  Try asking Onyx to summarize Threads by tagging the Onyx Slack Bot in the Thread!\n"
    "## Try it out\n"
    "The Onyx Slack Bot is always live and serving answers to the community in our public Slack.\n"
    "To test it out,\n"
    "join the [community Slack](https://join.slack.com/t/onyx-dot-app/shared_invite/zt-34lu4m7xg-TsKGO6h8PDvR5W27zTdyhA)\n"
    "and see the #ask-onyx channel or tag **@OnyxBot** from anywhere.\n"
)
onyx_anywhere_web_interface_title = "Web App"
onyx_anywhere_web_interface = (
    "The Web App is the default way to use Onyx and the recommended for the most complete experience.\n"
    "The admin panel is also a web-app exclusive feature which is the easiest way to manage the\n"
    "[Agents](/overview/core_features/agents), [Actions](/overview/core_features/actions),\n"
    "[Connectors](/overview/core_features/connectors), users, settings and more.\n"
    "  A great place to get familiar with the experience is to start with the [Chat](/overview/core_features/chat)\n"
    "  overview or the [Admin](/admin/overview) tab for managing the deployment.\n"
    "If you're deploying Onyx locally (guide [here](/deployment/getting_started/quickstart)),\n"
    "you should be able to access the Web UI at http://localhost:3000/.\n"
)

# For simplicity, we're not adding any metadata suffix here. Generally there is none for the Web connector anyway

# Welcome
welcome_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/welcome",
    title=welcome_title,
    content=welcome,
    title_embedding=list(model.encode(f"search_document: {welcome_title}")),
    content_embedding=list(
        model.encode(f"search_document: {welcome_title}\n{welcome}")
    ),
)

# Core Features
core_features_actions_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/core_features/actions",
    title=core_features_actions_title,
    content=core_features_actions,
    title_embedding=list(
        model.encode(f"search_document: {core_features_actions_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {core_features_actions_title}\n{core_features_actions}"
        )
    ),
)

core_features_agents_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/core_features/agents",
    title=core_features_agents_title,
    content=core_features_agents,
    title_embedding=list(
        model.encode(f"search_document: {core_features_agents_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {core_features_agents_title}\n{core_features_agents}"
        )
    ),
)

core_features_chat_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/core_features/chat",
    title=core_features_chat_title,
    content=core_features_chat,
    title_embedding=list(model.encode(f"search_document: {core_features_chat_title}")),
    content_embedding=list(
        model.encode(
            f"search_document: {core_features_chat_title}\n{core_features_chat}"
        )
    ),
)

core_features_code_interpreter_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/core_features/code_interpreter",
    title=core_features_code_interpreter_title,
    content=core_features_code_interpreter,
    title_embedding=list(
        model.encode(f"search_document: {core_features_code_interpreter_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {core_features_code_interpreter_title}\n{core_features_code_interpreter}"
        )
    ),
)

core_features_connectors_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/core_features/connectors",
    title=core_features_connectors_title,
    content=core_features_connectors,
    title_embedding=list(
        model.encode(f"search_document: {core_features_connectors_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {core_features_connectors_title}\n{core_features_connectors}"
        )
    ),
)

core_features_image_generation_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/core_features/image_generation",
    title=core_features_image_generation_title,
    content=core_features_image_generation,
    title_embedding=list(
        model.encode(f"search_document: {core_features_image_generation_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {core_features_image_generation_title}\n{core_features_image_generation}"
        )
    ),
)

core_features_internal_search_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/core_features/internal_search",
    title=core_features_internal_search_title,
    content=core_features_internal_search,
    title_embedding=list(
        model.encode(f"search_document: {core_features_internal_search_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {core_features_internal_search_title}\n{core_features_internal_search}"
        )
    ),
)

core_features_web_search_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/core_features/web_search",
    title=core_features_web_search_title,
    content=core_features_web_search,
    title_embedding=list(
        model.encode(f"search_document: {core_features_web_search_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {core_features_web_search_title}\n{core_features_web_search}"
        )
    ),
)

core_features_workflows_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/core_features/workflows",
    title=core_features_workflows_title,
    content=core_features_workflows,
    title_embedding=list(
        model.encode(f"search_document: {core_features_workflows_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {core_features_workflows_title}\n{core_features_workflows}"
        )
    ),
)

# Getting Started
getting_started_faq_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/getting_started/faq",
    title=getting_started_faq_title,
    content=getting_started_faq,
    title_embedding=list(model.encode(f"search_document: {getting_started_faq_title}")),
    content_embedding=list(
        model.encode(
            f"search_document: {getting_started_faq_title}\n{getting_started_faq}"
        )
    ),
)

getting_started_use_cases_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/getting_started/use_cases",
    title=getting_started_use_cases_title,
    content=getting_started_use_cases,
    title_embedding=list(
        model.encode(f"search_document: {getting_started_use_cases_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {getting_started_use_cases_title}\n{getting_started_use_cases}"
        )
    ),
)

# Miscellaneous
miscellaneous_contact_us_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/miscellaneous/contact_us",
    title=miscellaneous_contact_us_title,
    content=miscellaneous_contact_us,
    title_embedding=list(
        model.encode(f"search_document: {miscellaneous_contact_us_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {miscellaneous_contact_us_title}\n{miscellaneous_contact_us}"
        )
    ),
)

miscellaneous_open_source_statement_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/miscellaneous/open_source_statement",
    title=miscellaneous_open_source_statement_title,
    content=miscellaneous_open_source_statement,
    title_embedding=list(
        model.encode(f"search_document: {miscellaneous_open_source_statement_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {miscellaneous_open_source_statement_title}\n{miscellaneous_open_source_statement}"
        )
    ),
)

# Onyx Anywhere
onyx_anywhere_chrome_extension_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/onyx_anywhere/chrome_extension",
    title=onyx_anywhere_chrome_extension_title,
    content=onyx_anywhere_chrome_extension,
    title_embedding=list(
        model.encode(f"search_document: {onyx_anywhere_chrome_extension_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {onyx_anywhere_chrome_extension_title}\n{onyx_anywhere_chrome_extension}"
        )
    ),
)

onyx_anywhere_mobile_app_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/onyx_anywhere/mobile_app",
    title=onyx_anywhere_mobile_app_title,
    content=onyx_anywhere_mobile_app,
    title_embedding=list(
        model.encode(f"search_document: {onyx_anywhere_mobile_app_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {onyx_anywhere_mobile_app_title}\n{onyx_anywhere_mobile_app}"
        )
    ),
)

onyx_anywhere_slack_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/onyx_anywhere/slack",
    title=onyx_anywhere_slack_title,
    content=onyx_anywhere_slack,
    title_embedding=list(model.encode(f"search_document: {onyx_anywhere_slack_title}")),
    content_embedding=list(
        model.encode(
            f"search_document: {onyx_anywhere_slack_title}\n{onyx_anywhere_slack}"
        )
    ),
)

onyx_anywhere_web_interface_doc = SeedPresaveDocument(
    url=DOCUMENTATION_BASE_URL + "/overview/onyx_anywhere/web_interface",
    title=onyx_anywhere_web_interface_title,
    content=onyx_anywhere_web_interface,
    title_embedding=list(
        model.encode(f"search_document: {onyx_anywhere_web_interface_title}")
    ),
    content_embedding=list(
        model.encode(
            f"search_document: {onyx_anywhere_web_interface_title}\n{onyx_anywhere_web_interface}"
        )
    ),
)

documents = [
    # Welcome
    welcome_doc,
    # Core Features
    core_features_actions_doc,
    core_features_agents_doc,
    core_features_chat_doc,
    core_features_code_interpreter_doc,
    core_features_connectors_doc,
    core_features_image_generation_doc,
    core_features_internal_search_doc,
    core_features_web_search_doc,
    core_features_workflows_doc,
    # Getting Started
    getting_started_faq_doc,
    getting_started_use_cases_doc,
    # Miscellaneous
    miscellaneous_contact_us_doc,
    miscellaneous_open_source_statement_doc,
    # Onyx Anywhere
    onyx_anywhere_chrome_extension_doc,
    onyx_anywhere_mobile_app_doc,
    onyx_anywhere_slack_doc,
    onyx_anywhere_web_interface_doc,
]

documents_dict = [doc.model_dump() for doc in documents]

with open("./backend/onyx/seeding/initial_docs.json", "w") as json_file:
    json.dump(documents_dict, json_file, indent=4)
