import { expect, Page, test } from "@playwright/test";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import {
  buildMockSearchStream,
  buildMockStream,
  mockChatEndpoint,
  mockChatEndpointSequence,
  type MockDocument,
  resetTurnCounter,
} from "@tests/e2e/utils/chatMock";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";

const SHORT_USER_MESSAGE = "What is Onyx?";

const LONG_WORD_USER_MESSAGE =
  "Please look into this issue: __________________________________________ and also this token: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA and this URL: https://example.com/a/very/long/path/that/keeps/going/and/going/and/going/without/any/breaks/whatsoever/to/test/overflow";

const LONG_USER_MESSAGE = `I've been evaluating several enterprise search and AI platforms for our organization, and I have a number of detailed questions about Onyx that I'd like to understand before we make a decision.

First, can you explain how Onyx handles document indexing across multiple data sources? We currently use Confluence, Google Drive, Slack, and GitHub, and we need to ensure that all of these can be indexed simultaneously without performance degradation.

Second, I'm interested in understanding the security model. Specifically, how does Onyx handle document-level permissions when syncing from sources that have their own ACL systems? Does it respect the original source permissions, or does it create its own permission layer?

Third, we have a requirement for real-time or near-real-time indexing. What is the typical latency between a document being updated in a source system and it becoming searchable in Onyx?

Finally, could you walk me through the architecture of the AI chat system? How does it decide which documents to reference when answering a question, and how does it handle cases where the retrieved documents might contain conflicting information?`;

const SHORT_AI_RESPONSE =
  "Onyx is an open-source AI-powered enterprise search platform that connects to your company's documents, apps, and people.";

const LONG_AI_RESPONSE = `Onyx is an open-source Gen-AI and Enterprise Search platform designed to connect to your company's documents, applications, and people. Let me address each of your questions in detail.

## Document Indexing

Onyx uses a **connector-based architecture** where each data source has a dedicated connector. These connectors run as background workers and can index simultaneously without interfering with each other. The supported connectors include:

- **Confluence** — Full page and space indexing with attachment support
- **Google Drive** — File and folder indexing with shared drive support
- **Slack** — Channel message indexing with thread support
- **GitHub** — Repository, issue, and pull request indexing

Each connector runs on its own schedule and can be configured independently for polling frequency.

## Security Model

Onyx implements a **document-level permission system** that syncs with source ACLs. When documents are indexed, their permissions are preserved:

\`\`\`
Source Permission → Onyx ACL Sync → Query-time Filtering
\`\`\`

This means that when a user searches, they only see documents they have access to in the original source system. The permission sync runs periodically to stay up to date.

## Indexing Latency

The typical indexing latency depends on your configuration:

1. **Polling mode**: Documents are picked up on the next polling cycle (configurable, default 10 minutes)
2. **Webhook mode**: Near real-time, typically under 30 seconds
3. **Manual trigger**: Immediate indexing on demand

## AI Chat Architecture

The chat system uses a **Retrieval-Augmented Generation (RAG)** pipeline:

1. User query is analyzed and expanded
2. Relevant documents are retrieved from the vector database (Vespa)
3. Documents are ranked and filtered by relevance and permissions
4. The LLM generates a response grounded in the retrieved documents
5. Citations are attached to specific claims in the response

When documents contain conflicting information, the system presents the most relevant and recent information first, and includes citations so users can verify the source material themselves.`;

const MARKDOWN_AI_RESPONSE = `Here's a quick overview with various formatting:

### Key Features

| Feature | Status | Notes |
|---------|--------|-------|
| Enterprise Search | ✅ Available | Full-text and semantic |
| AI Chat | ✅ Available | Multi-model support |
| Connectors | ✅ Available | 30+ integrations |
| Permissions | ✅ Available | Source ACL sync |

### Code Example

\`\`\`python
from onyx import OnyxClient

client = OnyxClient(api_key="your-key")
results = client.search("quarterly revenue report")

for doc in results:
    print(f"{doc.title}: {doc.score:.2f}")
\`\`\`

> **Note**: Onyx supports both cloud and self-hosted deployments. The self-hosted option gives you full control over your data.

Key benefits include:

- **Privacy**: Your data stays within your infrastructure
- **Flexibility**: Connect any data source via custom connectors
- **Extensibility**: Open-source codebase with active community`;

const LATEX_AI_RESPONSE = `Here is a mix of math and plain text:

Inline math should render cleanly: \\(E = mc^2\\).

Display math should render on its own line:
\\[
\\int_0^1 x^2 \\, dx = \\frac{1}{3}
\\]

This currency value should stay plain text: $100.

And this LaTeX source should remain a code block:
\`\`\`latex
\\int_0^1 x^2 \\, dx = \\frac{1}{3}
\`\`\``;

for (const theme of THEMES) {
  test.describe(`Chat Message Rendering (${theme} mode)`, () => {
    let chat: ChatPage;

    test.beforeEach(async ({ page }, testInfo) => {
      resetTurnCounter();
      chat = new ChatPage(page);
      await page.context().clearCookies();
      await setThemeBeforeNavigation(page, theme);
      await loginAsWorkerUser(page, testInfo.workerIndex);
    });

    test.describe("Short Messages", () => {
      test("short user message with short AI response renders correctly", async ({
        page,
      }) => {
        await chat.goto();
        await mockChatEndpoint(page, buildMockStream(SHORT_AI_RESPONSE));

        await sendMessage(page, SHORT_USER_MESSAGE);

        const userMessage = page.locator("#onyx-human-message").first();
        await expect(userMessage).toContainText(SHORT_USER_MESSAGE);

        const aiMessage = page.getByTestId("onyx-ai-message").first();
        await expect(aiMessage).toContainText("open-source AI-powered");

        await chat.screenshotContainer(
          `chat-short-message-short-response-${theme}`
        );
      });
    });

    test.describe("Long Messages", () => {
      test("long user message renders without truncation", async ({ page }) => {
        await chat.goto();
        await mockChatEndpoint(page, buildMockStream(SHORT_AI_RESPONSE));

        await sendMessage(page, LONG_USER_MESSAGE);

        const userMessage = page.locator("#onyx-human-message").first();
        await expect(userMessage).toContainText("document indexing");
        await expect(userMessage).toContainText("security model");
        await expect(userMessage).toContainText("real-time or near-real-time");
        await expect(userMessage).toContainText("architecture of the AI chat");

        await chat.screenshotContainer(
          `chat-long-user-message-short-response-${theme}`
        );
      });

      test("long AI response with markdown renders correctly", async ({
        page,
      }) => {
        await chat.goto();
        await mockChatEndpoint(page, buildMockStream(LONG_AI_RESPONSE));

        await sendMessage(page, SHORT_USER_MESSAGE);

        const aiMessage = page.getByTestId("onyx-ai-message").first();
        await expect(aiMessage).toContainText("Document Indexing");
        await expect(aiMessage).toContainText("Security Model");
        await expect(aiMessage).toContainText("Indexing Latency");
        await expect(aiMessage).toContainText("AI Chat Architecture");

        await chat.screenshotContainerTopAndBottom(
          `chat-short-message-long-response-${theme}`
        );
      });

      test("user message with very long words wraps without overflowing", async ({
        page,
      }) => {
        await chat.goto();
        await mockChatEndpoint(page, buildMockStream(SHORT_AI_RESPONSE));

        await sendMessage(page, LONG_WORD_USER_MESSAGE);

        const userMessage = page.locator("#onyx-human-message").first();
        await expect(userMessage).toContainText("__________");

        await chat.screenshotContainer(`chat-long-word-user-message-${theme}`);

        // Assert the message bubble does not overflow horizontally.
        const overflows = await userMessage.evaluate((el) => {
          const bubble = el.querySelector<HTMLElement>(
            ".whitespace-break-spaces"
          );
          if (!bubble)
            throw new Error(
              "Expected human message bubble (.whitespace-break-spaces) to exist"
            );
          return bubble.scrollWidth > bubble.offsetWidth;
        });
        expect(overflows).toBe(false);
      });

      test("long user message with long AI response renders correctly", async ({
        page,
      }) => {
        await chat.goto();
        await mockChatEndpoint(page, buildMockStream(LONG_AI_RESPONSE));

        await sendMessage(page, LONG_USER_MESSAGE);

        const userMessage = page.locator("#onyx-human-message").first();
        await expect(userMessage).toContainText("document indexing");

        const aiMessage = page.getByTestId("onyx-ai-message").first();
        await expect(aiMessage).toContainText("Retrieval-Augmented Generation");

        await chat.screenshotContainerTopAndBottom(
          `chat-long-message-long-response-${theme}`
        );
      });
    });

    test.describe("Markdown and Code Rendering", () => {
      test("AI response with tables and code blocks renders correctly", async ({
        page,
      }) => {
        await chat.goto();
        await mockChatEndpoint(page, buildMockStream(MARKDOWN_AI_RESPONSE));

        await sendMessage(page, "Give me an overview of Onyx features");

        const aiMessage = page.getByTestId("onyx-ai-message").first();
        await expect(aiMessage).toContainText("Key Features");
        await expect(aiMessage).toContainText("OnyxClient");
        await expect(aiMessage).toContainText("Privacy");

        await chat.screenshotContainer(`chat-markdown-code-response-${theme}`);
      });

      test("AI response with LaTeX math renders correctly", async ({
        page,
      }) => {
        await chat.goto();
        await mockChatEndpoint(page, buildMockStream(LATEX_AI_RESPONSE));

        await sendMessage(page, "Show me inline and block math");

        const aiMessage = page.getByTestId("onyx-ai-message").first();

        await chat.screenshotContainer(`chat-latex-math-response-${theme}`);

        await expect(aiMessage).toContainText("Inline math should render");
        await expect(aiMessage).toContainText(
          "This currency value should stay plain text: $100."
        );
        await expect(aiMessage.locator(".katex")).toHaveCount(2);
        await expect(aiMessage.locator(".katex-display")).toBeVisible();
        await expect(aiMessage.getByRole("code")).toContainText(
          "\\int_0^1 x^2 \\, dx = \\frac{1}{3}"
        );
      });
    });

    test.describe("Multi-Turn Conversation", () => {
      test("multi-turn conversation renders all messages correctly", async ({
        page,
      }) => {
        await chat.goto();

        const responses = [
          SHORT_AI_RESPONSE,
          "Yes, Onyx supports over 30 data source connectors including Confluence, Google Drive, Slack, GitHub, Jira, Notion, and many more.",
          "To get started, you can deploy Onyx using Docker Compose with a single command. The setup takes about 5 minutes.",
        ];

        await mockChatEndpointSequence(page, responses);

        await sendMessage(page, SHORT_USER_MESSAGE);
        await expect(page.getByTestId("onyx-ai-message").first()).toContainText(
          "open-source AI-powered"
        );

        await sendMessage(page, "What connectors does it support?");
        await expect(page.getByTestId("onyx-ai-message")).toHaveCount(2, {
          timeout: 30000,
        });

        await sendMessage(page, "How do I get started?");
        await expect(page.getByTestId("onyx-ai-message")).toHaveCount(3, {
          timeout: 30000,
        });

        const userMessages = page.locator("#onyx-human-message");
        await expect(userMessages).toHaveCount(3);

        await chat.screenshotContainerTopAndBottom(
          `chat-multi-turn-conversation-${theme}`
        );
      });

      test("multi-turn with mixed message lengths renders correctly", async ({
        page,
      }) => {
        await chat.goto();

        const responses = [LONG_AI_RESPONSE, SHORT_AI_RESPONSE];

        await mockChatEndpointSequence(page, responses);

        await sendMessage(page, LONG_USER_MESSAGE);
        await expect(page.getByTestId("onyx-ai-message").first()).toContainText(
          "Document Indexing"
        );

        await sendMessage(page, SHORT_USER_MESSAGE);
        await expect(page.getByTestId("onyx-ai-message")).toHaveCount(2, {
          timeout: 30000,
        });

        await chat.screenshotContainerTopAndBottom(
          `chat-multi-turn-mixed-lengths-${theme}`
        );
      });
    });

    test.describe("Web Search with Citations", () => {
      const TOOLBAR_BUTTONS = [
        "AgentMessage/copy-button",
        "AgentMessage/like-button",
        "AgentMessage/dislike-button",
      ] as const;

      async function screenshotToolbarButtonHoverStates(
        page: Page,
        namePrefix: string
      ): Promise<void> {
        const aiMessage = page.getByTestId("onyx-ai-message").first();
        const toolbar = aiMessage.getByTestId("AgentMessage/toolbar");
        await expect(toolbar).toBeVisible({ timeout: 10000 });

        await toolbar.scrollIntoViewIfNeeded();
        await page.evaluate(
          () => new Promise<void>((r) => requestAnimationFrame(() => r()))
        );

        for (const buttonTestId of TOOLBAR_BUTTONS) {
          const button = aiMessage.getByTestId(buttonTestId);
          await button.hover();
          const buttonSlug = buttonTestId.split("/")[1];
          await expectElementScreenshot(toolbar, {
            name: `${namePrefix}-toolbar-${buttonSlug}-hover-${theme}`,
          });
        }

        // Sources tag is located by role+name since SourceTag has no testid.
        const sourcesButton = toolbar.getByRole("button", { name: "Sources" });
        if (await sourcesButton.isVisible()) {
          await sourcesButton.hover();
          await expectElementScreenshot(toolbar, {
            name: `${namePrefix}-toolbar-sources-hover-${theme}`,
          });
        }

        // LLMPopover trigger is only rendered when the regenerate action is
        // available (requires onRegenerate + parentMessage + llmManager props).
        const llmTrigger = aiMessage.getByTestId("llm-popover-trigger");
        if (await llmTrigger.isVisible()) {
          await llmTrigger.hover();
          await expectElementScreenshot(toolbar, {
            name: `${namePrefix}-toolbar-llm-popover-hover-${theme}`,
          });
        }
      }

      const WEB_SEARCH_DOCUMENTS: MockDocument[] = [
        {
          document_id: "web-doc-1",
          semantic_identifier: "Onyx Documentation - Getting Started",
          link: "https://docs.onyx.app/getting-started",
          source_type: "web",
          blurb:
            "Onyx is an open-source enterprise search and AI platform. Deploy in minutes with Docker Compose.",
          is_internet: true,
        },
        {
          document_id: "web-doc-2",
          semantic_identifier: "Onyx GitHub Repository",
          link: "https://github.com/onyx-dot-app/onyx",
          source_type: "web",
          blurb:
            "Open-source Gen-AI platform with 30+ connectors. MIT licensed community edition.",
          is_internet: true,
        },
        {
          document_id: "web-doc-3",
          semantic_identifier: "Enterprise Search Comparison 2025",
          link: "https://example.com/enterprise-search-comparison",
          source_type: "web",
          blurb:
            "Comparing top enterprise search platforms including Onyx, Glean, and Coveo.",
          is_internet: true,
        },
      ];

      const WEB_SEARCH_RESPONSE = `Based on my web search, here's what I found about Onyx:

Onyx is an open-source enterprise search and AI platform that can be deployed in minutes using Docker Compose [[D1]](https://docs.onyx.app/getting-started). The project is hosted on GitHub and is MIT licensed for the community edition, with over 30 connectors available [[D2]](https://github.com/onyx-dot-app/onyx).

In comparisons with other enterprise search platforms, Onyx stands out for its open-source nature and self-hosted deployment option [[D3]](https://example.com/enterprise-search-comparison). Unlike proprietary alternatives, you maintain full control over your data and infrastructure.

Key advantages include:

- **Self-hosted**: Deploy on your own infrastructure
- **Open source**: Full visibility into the codebase [[D2]](https://github.com/onyx-dot-app/onyx)
- **Quick setup**: Get running in under 5 minutes [[D1]](https://docs.onyx.app/getting-started)
- **Extensible**: 30+ pre-built connectors with custom connector support`;

      test("web search response with citations renders correctly", async ({
        page,
      }) => {
        await chat.goto();

        await page.route("**/api/chat/send-chat-message", async (route) => {
          await route.fulfill({
            status: 200,
            contentType: "text/plain",
            body: buildMockSearchStream({
              content: WEB_SEARCH_RESPONSE,
              queries: ["Onyx enterprise search platform overview"],
              documents: WEB_SEARCH_DOCUMENTS,
              citations: {
                1: "web-doc-1",
                2: "web-doc-2",
                3: "web-doc-3",
              },
              isInternetSearch: true,
            }),
          });
        });

        await sendMessage(page, "Search the web for information about Onyx");

        const aiMessage = page.getByTestId("onyx-ai-message").first();
        await expect(aiMessage).toContainText("open-source enterprise search");
        await expect(aiMessage).toContainText("Docker Compose");
        await expect(aiMessage).toContainText("MIT licensed");

        await chat.screenshotContainer(
          `chat-web-search-with-citations-${theme}`
        );

        await screenshotToolbarButtonHoverStates(page, "chat-web-search");
      });

      test("internal document search response renders correctly", async ({
        page,
      }) => {
        const internalDocs: MockDocument[] = [
          {
            document_id: "confluence-doc-1",
            semantic_identifier: "Q3 2025 Engineering Roadmap",
            link: "https://company.atlassian.net/wiki/spaces/ENG/pages/123",
            source_type: "confluence",
            blurb:
              "Engineering priorities for Q3 include platform stability, new connector integrations, and performance improvements.",
            is_internet: false,
          },
          {
            document_id: "gdrive-doc-1",
            semantic_identifier: "Platform Architecture Overview.pdf",
            link: "https://drive.google.com/file/d/abc123",
            source_type: "google_drive",
            blurb:
              "Onyx platform architecture document covering microservices, data flow, and deployment topology.",
            is_internet: false,
          },
        ];

        const internalResponse = `Based on your company's internal documents, here is the engineering roadmap:

The Q3 2025 priorities focus on three main areas [[D1]](https://company.atlassian.net/wiki/spaces/ENG/pages/123):

1. **Platform stability** — Improving error handling and retry mechanisms across all connectors
2. **New integrations** — Adding support for ServiceNow and Zendesk connectors
3. **Performance** — Optimizing vector search latency and reducing indexing time

The platform architecture document provides additional context on how these improvements fit into the overall system design [[D2]](https://drive.google.com/file/d/abc123). The microservices architecture allows each component to be scaled independently.`;

        await chat.goto();

        await page.route("**/api/chat/send-chat-message", async (route) => {
          await route.fulfill({
            status: 200,
            contentType: "text/plain",
            body: buildMockSearchStream({
              content: internalResponse,
              queries: ["Q3 engineering roadmap priorities"],
              documents: internalDocs,
              citations: {
                1: "confluence-doc-1",
                2: "gdrive-doc-1",
              },
              isInternetSearch: false,
            }),
          });
        });

        await sendMessage(page, "What are our engineering priorities for Q3?");

        const aiMessage = page.getByTestId("onyx-ai-message").first();
        await expect(aiMessage).toContainText("Platform stability");
        await expect(aiMessage).toContainText("New integrations");
        await expect(aiMessage).toContainText("Performance");

        await chat.screenshotContainer(
          `chat-internal-search-with-citations-${theme}`
        );

        await screenshotToolbarButtonHoverStates(page, "chat-internal-search");
      });
    });

    test.describe("Header Levels", () => {
      const HEADINGS_RESPONSE = `# Getting Started

This is the introductory paragraph.

## Installing the \`onyx-sdk\`

Follow these steps to install the SDK.

### Configuration Options

Some details about configuration.

#### The \`max_results\` Parameter

Set \`max_results\` to limit the number of returned documents.`;

      test("h1 through h4 headings with inline code render correctly", async ({
        page,
      }) => {
        await chat.goto();
        await mockChatEndpoint(page, buildMockStream(HEADINGS_RESPONSE));

        await sendMessage(page, "Show me all heading levels");

        const aiMessage = page.getByTestId("onyx-ai-message").first();

        await expect(aiMessage.locator("h1")).toContainText("Getting Started");
        await expect(aiMessage.locator("h2")).toContainText("Installing the");
        await expect(
          aiMessage.locator("h2").locator('[data-testid="code-block"]')
        ).toContainText("onyx-sdk");
        await expect(aiMessage.locator("h3")).toContainText(
          "Configuration Options"
        );
        await expect(aiMessage.locator("h4")).toContainText("Parameter");
        await expect(
          aiMessage.locator("h4").locator('[data-testid="code-block"]')
        ).toContainText("max_results");

        await expect(aiMessage.locator("h1")).toHaveCount(1);
        await expect(aiMessage.locator("h2")).toHaveCount(1);
        await expect(aiMessage.locator("h3")).toHaveCount(1);
        await expect(aiMessage.locator("h4")).toHaveCount(1);

        await chat.screenshotContainer(`chat-heading-levels-h1-h4-${theme}`);
      });
    });

    test.describe("Message Interaction States", () => {
      test("hovering over user message shows action buttons", async ({
        page,
      }) => {
        await chat.goto();
        await mockChatEndpoint(page, buildMockStream(SHORT_AI_RESPONSE));

        await sendMessage(page, SHORT_USER_MESSAGE);

        const userMessage = page.locator("#onyx-human-message").first();
        await userMessage.hover();

        const editButton = userMessage.getByTestId("HumanMessage/edit-button");
        await expect(editButton).toBeVisible({ timeout: 5000 });

        await chat.screenshotContainer(
          `chat-user-message-hover-state-${theme}`
        );
      });

      test("AI message toolbar is visible after response completes", async ({
        page,
      }) => {
        await chat.goto();
        await mockChatEndpoint(page, buildMockStream(SHORT_AI_RESPONSE));

        await sendMessage(page, SHORT_USER_MESSAGE);

        const aiMessage = page.getByTestId("onyx-ai-message").first();

        const copyButton = aiMessage.getByTestId("AgentMessage/copy-button");
        const likeButton = aiMessage.getByTestId("AgentMessage/like-button");
        const dislikeButton = aiMessage.getByTestId(
          "AgentMessage/dislike-button"
        );

        await expect(copyButton).toBeVisible({ timeout: 10000 });
        await expect(likeButton).toBeVisible();
        await expect(dislikeButton).toBeVisible();

        await chat.screenshotContainer(`chat-ai-message-with-toolbar-${theme}`);
      });
    });
  });
}
