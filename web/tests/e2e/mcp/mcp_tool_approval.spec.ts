import { test, expect, type Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  startMcpApiKeyServer,
  McpServerProcess,
} from "@tests/e2e/utils/mcpServer";
import {
  addMockLlmConversation,
  getMockLlmConversationRequests,
  mockLlmNonce,
  mockLlmToolCallReply,
} from "@tests/e2e/utils/mockLlm";
import { qualifiedMcpToolName } from "@tests/e2e/mcp/mcpToolInvocation";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { ToolApprovalCard } from "@tests/e2e/pages/ToolApprovalCard";

const API_KEY = process.env.MCP_API_KEY || "test-api-key-12345";
const PORT = Number(process.env.MCP_APPROVAL_TEST_PORT || "8008");
// A shared mock server gets a query string, so specs that clean up servers by
// URL never delete this spec's server.
const SHARED_SERVER_URL = process.env.MCP_API_KEY_TEST_URL
  ? `${process.env.MCP_API_KEY_TEST_URL}?spec=tool-approval`
  : null;
const TOOL_NAME = "tool_0";
const TOOL_OUTPUT = "Secret value 200!";

/**
 * An MCP tool on the default (ASK) policy pauses the chat run until the user
 * approves or rejects the call in the answer's approval card.
 */
test.describe("MCP tool approval in chat @code-mode", () => {
  test.describe.configure({ mode: "serial" });

  let serverProcess: McpServerProcess | null = null;
  let serverId: number;
  let agentId: number;
  let agentName: string;
  let qualifiedToolName: string;
  let toolDisplayName: string;

  test.beforeAll(async ({ browser }) => {
    let serverUrl = SHARED_SERVER_URL;
    if (!serverUrl) {
      serverProcess = await startMcpApiKeyServer({
        port: PORT,
        apiKey: API_KEY,
      });
      serverUrl = `http://${serverProcess.address.host}:${serverProcess.address.port}/mcp`;
    }

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);
    const serverName = `PW Approval Server ${Date.now()}`;
    serverId = await adminClient.createMcpServerWithAuth({
      name: serverName,
      description: "MCP server whose tools ask for approval (e2e)",
      server_url: serverUrl,
      auth_type: "API_TOKEN",
      auth_performer: "ADMIN",
      api_token: API_KEY,
    });
    await adminClient.discoverMcpTools(serverId);
    const toolId = await adminClient.findMcpToolId(serverId, TOOL_NAME);
    const tool = (await adminClient.getMcpDbTools(serverId)).find(
      (dbTool) => dbTool.id === toolId
    );
    toolDisplayName = tool?.display_name || TOOL_NAME;
    qualifiedToolName = qualifiedMcpToolName(serverId, serverName, TOOL_NAME);
    agentName = `PW Approval Agent ${Date.now()}`;
    agentId = await adminClient.createAgentWithMcpTools(agentName, [toolId]);
    await adminContext.close();
  });

  test.afterAll(async ({ browser }) => {
    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);
    if (agentId) await adminClient.deleteAgent(agentId);
    if (serverId) await adminClient.deleteMcpServer(serverId);
    await adminContext.close();
    await serverProcess?.stop();
  });

  /**
   * Script a turn that calls the tool, then, unless the test stops the turn,
   * answers once it has a result. Starts a new chat unless `sameChat`.
   */
  async function askForToolCall(
    page: Page,
    { sameChat = false, answers = true } = {}
  ): Promise<{ nonce: string; answer: string; conversation: string }> {
    const nonce = mockLlmNonce();
    const callId = `call-${nonce}`;
    const answer = `Finished ${nonce}`;
    const conversation = `approval-${nonce}`;
    await addMockLlmConversation({
      name: conversation,
      conditions: { prompt_contains: [nonce] },
      replies: [
        // Code mode calls the tool from an execute_code program.
        mockLlmToolCallReply([
          { id: callId, name: qualifiedToolName, arguments: { name: nonce } },
        ]),
        ...(answers
          ? [{ text: answer, conditions: { has_results_for: [callId] } }]
          : []),
      ],
    });
    const chat = new ChatPage(page);
    if (!sameChat) await chat.gotoAgent(agentId, agentName);
    await chat.inputBar.fill(`Call ${TOOL_NAME} with ${nonce}`);
    await chat.inputBar.send();
    return { nonce, answer, conversation };
  }

  test("Approve runs the tool and the answer continues", async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const { nonce, answer } = await askForToolCall(page);

    const card = new ToolApprovalCard(page);
    await card.expectPending(toolDisplayName);
    await card.expectArgument(nonce);
    const chat = new ChatPage(page);

    await test.step("a send waits for the decision and keeps the draft", async () => {
      const draft = `Next question ${nonce}`;
      await chat.scrollTo("top");
      await chat.inputBar.fill(draft);
      await chat.inputBar.send();
      await card.expectSendBlocked();
      await expect(chat.inputBar.textbox).toHaveText(draft);
      await expect(chat.humanMessages).toHaveCount(1);
      await chat.inputBar.clear();
    });

    await card.approve();

    await card.expectApproved();
    await chat.expectLatestReplyComplete();
    await expect(chat.answerText(answer)).toBeVisible();
    await chat.expectCustomToolResult(toolDisplayName, TOOL_OUTPUT);
  });

  test("Reject skips the tool and the answer continues", async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const { answer, conversation } = await askForToolCall(page);

    const card = new ToolApprovalCard(page);
    await card.expectPending(toolDisplayName);
    await card.reject();

    await card.expectNotApproved();
    const chat = new ChatPage(page);
    await chat.expectLatestReplyComplete();
    await expect(chat.answerText(answer)).toBeVisible();
    // The call, or in code mode the program that made it, sees the rejection.
    const requests = await getMockLlmConversationRequests(conversation);
    expect(
      requests
        .flatMap((request) => request.messages)
        .some(
          (message) =>
            message.role === "tool" &&
            /The user rejected this/i.test(message.content)
        )
    ).toBe(true);
  });

  test("Approve for this chat runs later calls without asking", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const first = await askForToolCall(page);

    const card = new ToolApprovalCard(page);
    await card.expectPending(toolDisplayName);
    await card.approveForChat();
    await card.expectApprovedForChat();
    const chat = new ChatPage(page);
    await chat.expectLatestReplyComplete();
    await expect(chat.answerText(first.answer)).toBeVisible();

    // The next call in this chat runs at once.
    const second = await askForToolCall(page, { sameChat: true });
    await chat.expectLatestReplyComplete();
    await expect(chat.answerText(second.answer, 1)).toBeVisible();
    await expect(card.cards).toHaveCount(1);
    const requests = await getMockLlmConversationRequests(second.conversation);
    expect(
      requests
        .flatMap((request) => request.messages)
        .some(
          (message) =>
            message.role === "tool" && message.content.includes(TOOL_OUTPUT)
        )
    ).toBe(true);
  });

  test("A waiting card stays decidable after a reload", async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const { answer } = await askForToolCall(page);

    const card = new ToolApprovalCard(page);
    await card.expectPending(toolDisplayName);
    const chat = new ChatPage(page);
    await chat.reload();

    await card.expectPending(toolDisplayName);
    await card.approve();
    await card.expectApproved();
    await chat.expectLatestReplyComplete();
    await expect(chat.answerText(answer)).toBeVisible();
    await chat.expectCustomToolResult(toolDisplayName, TOOL_OUTPUT);
  });

  test("Stop closes a waiting card and the chat takes new messages", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await askForToolCall(page, { answers: false });

    const card = new ToolApprovalCard(page);
    await card.expectPending(toolDisplayName);
    const chat = new ChatPage(page);
    await chat.stop();
    await card.expectClosed();
    await chat.inputBar.expectIdle(30_000);

    const nonce = mockLlmNonce();
    await addMockLlmConversation({
      name: `after-stop-${nonce}`,
      conditions: { prompt_contains: [nonce] },
      replies: [{ text: `Hello again ${nonce}` }],
    });
    await chat.inputBar.fill(`Say hello ${nonce}`);
    await chat.inputBar.send();
    await chat.expectLatestReplyComplete();
    await expect(chat.answerText(`Hello again ${nonce}`, 1)).toBeVisible();
  });
});
