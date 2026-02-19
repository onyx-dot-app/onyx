import { expect, Page, test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";

const SHORT_USER_MESSAGE = "What is Onyx?";

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

interface MockDocument {
  document_id: string;
  semantic_identifier: string;
  link: string;
  source_type: string;
  blurb: string;
  is_internet: boolean;
}

interface SearchMockOptions {
  content: string;
  queries: string[];
  documents: MockDocument[];
  /** Maps citation number -> document_id */
  citations: Record<number, string>;
  isInternetSearch?: boolean;
}

let turnCounter = 0;

function buildMockStream(content: string): string {
  turnCounter += 1;
  const userMessageId = turnCounter * 100 + 1;
  const assistantMessageId = turnCounter * 100 + 2;

  const packets = [
    {
      user_message_id: userMessageId,
      reserved_assistant_message_id: assistantMessageId,
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: {
        type: "message_start",
        id: `mock-${assistantMessageId}`,
        content,
        final_documents: null,
      },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "stop", stop_reason: "finished" },
    },
    {
      message_id: assistantMessageId,
      citations: {},
      files: [],
    },
  ];

  return `${packets.map((p) => JSON.stringify(p)).join("\n")}\n`;
}

function buildMockSearchStream(options: SearchMockOptions): string {
  turnCounter += 1;
  const userMessageId = turnCounter * 100 + 1;
  const assistantMessageId = turnCounter * 100 + 2;

  const fullDocs = options.documents.map((doc) => ({
    ...doc,
    boost: 0,
    hidden: false,
    score: 0.95,
    chunk_ind: 0,
    match_highlights: [],
    metadata: {},
    updated_at: null,
  }));

  // Turn 0: search tool
  // Turn 1: answer + citations
  const packets: Record<string, unknown>[] = [
    {
      user_message_id: userMessageId,
      reserved_assistant_message_id: assistantMessageId,
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: {
        type: "search_tool_start",
        ...(options.isInternetSearch !== undefined && {
          is_internet_search: options.isInternetSearch,
        }),
      },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "search_tool_queries_delta", queries: options.queries },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "search_tool_documents_delta", documents: fullDocs },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "section_end" },
    },
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: "message_start",
        id: `mock-${assistantMessageId}`,
        content: options.content,
        final_documents: fullDocs,
      },
    },
    ...Object.entries(options.citations).map(([num, docId]) => ({
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: "citation_info",
        citation_number: Number(num),
        document_id: docId,
      },
    })),
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: { type: "stop", stop_reason: "finished" },
    },
    {
      message_id: assistantMessageId,
      citations: options.citations,
      files: [],
    },
  ];

  return `${packets.map((p) => JSON.stringify(p)).join("\n")}\n`;
}

async function openChat(page: Page): Promise<void> {
  await page.goto("/app");
  await page.waitForLoadState("networkidle");
  await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 15000 });
}

async function mockChatEndpoint(
  page: Page,
  responseContent: string
): Promise<void> {
  await page.route("**/api/chat/send-chat-message", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/plain",
      body: buildMockStream(responseContent),
    });
  });
}

async function mockChatEndpointSequence(
  page: Page,
  responses: string[]
): Promise<void> {
  let callIndex = 0;
  await page.route("**/api/chat/send-chat-message", async (route) => {
    const content =
      responses[Math.min(callIndex, responses.length - 1)] ??
      responses[responses.length - 1]!;
    callIndex += 1;
    await route.fulfill({
      status: 200,
      contentType: "text/plain",
      body: buildMockStream(content),
    });
  });
}

async function screenshotChatContainer(
  page: Page,
  name: string
): Promise<void> {
  const container = page.locator("[data-main-container]");
  await expect(container).toBeVisible();
  await expectElementScreenshot(container, { name });
}

/**
 * Captures two screenshots of the chat container for long-content tests:
 * one scrolled to the top and one scrolled to the bottom. Both are captured
 * for the current theme, ensuring consistent scroll positions regardless of
 * whether the page was just navigated to (top) or just finished streaming (bottom).
 */
async function screenshotChatContainerTopAndBottom(
  page: Page,
  name: string
): Promise<void> {
  const container = page.locator("[data-main-container]");
  await expect(container).toBeVisible();
  const scrollContainer = page.getByTestId("chat-scroll-container");

  await scrollContainer.evaluate((el) => el.scrollTo({ top: 0 }));
  await expectElementScreenshot(container, { name: `${name}-top` });

  await scrollContainer.evaluate((el) => el.scrollTo({ top: el.scrollHeight }));
  await expectElementScreenshot(container, { name: `${name}-bottom` });
}

for (const theme of THEMES) {
  test.describe(`Chat Message Rendering (${theme} mode)`, () => {
    test.beforeEach(async ({ page }, testInfo) => {
      turnCounter = 0;
      await page.context().clearCookies();
      await setThemeBeforeNavigation(page, theme);
      await loginAsWorkerUser(page, testInfo.workerIndex);
    });

    test.describe("Short Messages", () => {
      test("short user message with short AI response renders correctly", async ({
        page,
      }) => {
        await openChat(page);
        await mockChatEndpoint(page, SHORT_AI_RESPONSE);

        await sendMessage(page, SHORT_USER_MESSAGE);

        const userMessage = page.locator("#onyx-human-message").first();
        await expect(userMessage).toContainText(SHORT_USER_MESSAGE);

        const aiMessage = page.getByTestId("onyx-ai-message").first();
        await expect(aiMessage).toContainText("open-source AI-powered");

        await screenshotChatContainer(
          page,
          `chat-short-message-short-response-${theme}`
        );
      });
    });

    test.describe("Long Messages", () => {
      test("long user message renders without truncation", async ({ page }) => {
        await openChat(page);
        await mockChatEndpoint(page, SHORT_AI_RESPONSE);

        await sendMessage(page, LONG_USER_MESSAGE);

        const userMessage = page.locator("#onyx-human-message").first();
        await expect(userMessage).toContainText("document indexing");
        await expect(userMessage).toContainText("security model");
        await expect(userMessage).toContainText("real-time or near-real-time");
        await expect(userMessage).toContainText("architecture of the AI chat");

        await screenshotChatContainer(
          page,
          `chat-long-user-message-short-response-${theme}`
        );
      });

      test("long AI response with markdown renders correctly", async ({
        page,
      }) => {
        await openChat(page);
        await mockChatEndpoint(page, LONG_AI_RESPONSE);

        await sendMessage(page, SHORT_USER_MESSAGE);

        const aiMessage = page.getByTestId("onyx-ai-message").first();
        await expect(aiMessage).toContainText("Document Indexing");
        await expect(aiMessage).toContainText("Security Model");
        await expect(aiMessage).toContainText("Indexing Latency");
        await expect(aiMessage).toContainText("AI Chat Architecture");

        await screenshotChatContainerTopAndBottom(
          page,
          `chat-short-message-long-response-${theme}`
        );
      });

      test("long user message with long AI response renders correctly", async ({
        page,
      }) => {
        await openChat(page);
        await mockChatEndpoint(page, LONG_AI_RESPONSE);

        await sendMessage(page, LONG_USER_MESSAGE);

        const userMessage = page.locator("#onyx-human-message").first();
        await expect(userMessage).toContainText("document indexing");

        const aiMessage = page.getByTestId("onyx-ai-message").first();
        await expect(aiMessage).toContainText("Retrieval-Augmented Generation");

        await screenshotChatContainerTopAndBottom(
          page,
          `chat-long-message-long-response-${theme}`
        );
      });
    });

    test.describe("Markdown and Code Rendering", () => {
      test("AI response with tables and code blocks renders correctly", async ({
        page,
      }) => {
        await openChat(page);
        await mockChatEndpoint(page, MARKDOWN_AI_RESPONSE);

        await sendMessage(page, "Give me an overview of Onyx features");

        const aiMessage = page.getByTestId("onyx-ai-message").first();
        await expect(aiMessage).toContainText("Key Features");
        await expect(aiMessage).toContainText("OnyxClient");
        await expect(aiMessage).toContainText("Privacy");

        await screenshotChatContainer(
          page,
          `chat-markdown-code-response-${theme}`
        );
      });
    });

    test.describe("Multi-Turn Conversation", () => {
      test("multi-turn conversation renders all messages correctly", async ({
        page,
      }) => {
        await openChat(page);

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

        await screenshotChatContainerTopAndBottom(
          page,
          `chat-multi-turn-conversation-${theme}`
        );
      });

      test("multi-turn with mixed message lengths renders correctly", async ({
        page,
      }) => {
        await openChat(page);

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

        await screenshotChatContainerTopAndBottom(
          page,
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
        await openChat(page);

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

        await screenshotChatContainer(
          page,
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

        await openChat(page);

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

        await screenshotChatContainer(
          page,
          `chat-internal-search-with-citations-${theme}`
        );

        await screenshotToolbarButtonHoverStates(page, "chat-internal-search");
      });
    });

    test.describe("Message Interaction States", () => {
      test("hovering over user message shows action buttons", async ({
        page,
      }) => {
        await openChat(page);
        await mockChatEndpoint(page, SHORT_AI_RESPONSE);

        await sendMessage(page, SHORT_USER_MESSAGE);

        const userMessage = page.locator("#onyx-human-message").first();
        await userMessage.hover();

        const editButton = userMessage.getByTestId("HumanMessage/edit-button");
        await expect(editButton).toBeVisible({ timeout: 5000 });

        await screenshotChatContainer(
          page,
          `chat-user-message-hover-state-${theme}`
        );
      });

      test("AI message toolbar is visible after response completes", async ({
        page,
      }) => {
        await openChat(page);
        await mockChatEndpoint(page, SHORT_AI_RESPONSE);

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

        await screenshotChatContainer(
          page,
          `chat-ai-message-with-toolbar-${theme}`
        );
      });
    });
  });
}
