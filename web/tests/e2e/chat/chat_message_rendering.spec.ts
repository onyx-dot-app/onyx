import { expect, Page, test } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import {
  expectScreenshot,
  expectElementScreenshot,
} from "@tests/e2e/utils/visualRegression";

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

test.describe("Chat Message Rendering", () => {
  test.beforeEach(async ({ page }) => {
    turnCounter = 0;
    await page.context().clearCookies();
    await loginAs(page, "user");
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

      await expectScreenshot(page, {
        name: "chat-short-message-short-response",
        mask: ['[data-testid="AppSidebar/new-session"]'],
      });

      await expectElementScreenshot(userMessage, {
        name: "chat-short-user-message",
      });

      await expectElementScreenshot(aiMessage, {
        name: "chat-short-ai-response",
      });
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

      await expectElementScreenshot(userMessage, {
        name: "chat-long-user-message",
      });
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

      await expectScreenshot(page, {
        name: "chat-short-message-long-response",
        fullPage: true,
      });

      await expectElementScreenshot(aiMessage, {
        name: "chat-long-ai-response",
      });
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

      await expectScreenshot(page, {
        name: "chat-long-message-long-response",
        fullPage: true,
      });
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

      await expectElementScreenshot(aiMessage, {
        name: "chat-markdown-code-response",
      });
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

      await expectScreenshot(page, {
        name: "chat-multi-turn-conversation",
        fullPage: true,
      });
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

      await expectScreenshot(page, {
        name: "chat-multi-turn-mixed-lengths",
        fullPage: true,
      });
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

      await expectElementScreenshot(userMessage, {
        name: "chat-user-message-hover-state",
      });
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

      await expectElementScreenshot(aiMessage, {
        name: "chat-ai-message-with-toolbar",
      });
    });
  });
});
