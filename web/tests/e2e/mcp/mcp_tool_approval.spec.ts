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
import { CustomizeIntegrationPage } from "@tests/e2e/pages/CustomizeIntegrationPage";

const API_KEY = process.env.MCP_API_KEY || "test-api-key-12345";
// Without it, each server takes a free port.
const BASE_PORT = process.env.MCP_APPROVAL_TEST_PORT
  ? Number(process.env.MCP_APPROVAL_TEST_PORT)
  : undefined;
// A shared mock server gets a query string, so specs that clean up servers by
// URL never delete this spec's server.
const SHARED_SERVER_URL = process.env.MCP_API_KEY_TEST_URL
  ? `${process.env.MCP_API_KEY_TEST_URL}?spec=tool-approval`
  : null;
const TOOL_NAME = "tool_0";
const TOOL_OUTPUT = "Secret value 200!";
// Auto-approved; sleeps until the call is cancelled, so its turn stays live.
const SLOW_TOOL_NAME = "slow_tool";

/**
 * An MCP tool on the default (ASK) policy pauses the chat run until the user
 * approves or rejects the call in its approval card, which waits after the
 * last message. The turn's stream ends while it waits, and the reply
 * continues after the decision. The decision's record stays in the reply.
 */
test.describe("MCP tool approval in chat @code-mode", () => {
  test.describe.configure({ mode: "serial" });

  let serverProcess: McpServerProcess | null = null;
  let integrationId: number;
  let agentId: number;
  let agentName: string;
  let qualifiedToolName: string;
  let qualifiedSlowToolName: string;
  let toolDisplayName: string;

  test.beforeAll(async ({ browser }, workerInfo) => {
    let serverUrl = SHARED_SERVER_URL;
    if (!serverUrl) {
      // Projects that select this spec can run in parallel workers.
      const projectIndex = workerInfo.config.projects.findIndex(
        (project) => project.name === workerInfo.project.name
      );
      serverProcess = await startMcpApiKeyServer({
        port: BASE_PORT === undefined ? undefined : BASE_PORT + projectIndex,
        apiKey: API_KEY,
      });
      serverUrl = `http://${serverProcess.address.host}:${serverProcess.address.port}/mcp`;
    }

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);
    const serverName = `PW Approval Server ${Date.now()}`;
    const created = await adminClient.createIntegration({
      for_organization: true,
      name: serverName,
      description: "MCP server whose tools ask for approval (e2e)",
      auth_mode: "shared",
      auth_method: "api_key",
      credential_fields: [{ key: "api_key", label: "API Key", secret: true }],
      header_template: { Authorization: "Bearer {api_key}" },
      oauth_client: null,
      config: {
        shape: "mcp_server",
        server_url: serverUrl,
        transport: "STREAMABLE_HTTP",
      },
    });
    integrationId = created.id;
    const connect = await adminContext.request.put(
      `/api/admin/integrations/${integrationId}/organization-connection`,
      { data: { fields: { api_key: API_KEY } } }
    );
    expect(connect.ok(), await connect.text()).toBeTruthy();
    const { actions } =
      await adminClient.refreshIntegrationActions(integrationId);
    const tool = actions.find((action) => action.key === TOOL_NAME);
    if (!actions.some((action) => action.key === SLOW_TOOL_NAME) || !tool) {
      throw new Error(
        `Missing ${TOOL_NAME} or ${SLOW_TOOL_NAME}. Saw: ${actions
          .map((action) => action.key)
          .join(", ")}`
      );
    }
    toolDisplayName = tool.display_name;
    qualifiedToolName = qualifiedMcpToolName(
      integrationId,
      serverName,
      TOOL_NAME
    );
    await adminClient.setIntegrationActionPolicies(integrationId, {
      [SLOW_TOOL_NAME]: "allow",
    });
    qualifiedSlowToolName = qualifiedMcpToolName(
      integrationId,
      serverName,
      SLOW_TOOL_NAME
    );
    agentName = `PW Approval Agent ${Date.now()}`;
    agentId = await adminClient.createAgentWithIntegrations(agentName, [
      integrationId,
    ]);
    await adminContext.close();
  });

  test.afterAll(async ({ browser }) => {
    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);
    if (agentId) await adminClient.deleteAgent(agentId);
    if (integrationId) await adminClient.deleteIntegration(integrationId);
    await adminContext.close();
    await serverProcess?.stop();
  });

  /**
   * Script a turn that calls the tool, then, unless the test stops the turn,
   * answers once it has a result. With `slowSibling`, the turn also calls the
   * slow tool at the same time, so it stays live while the card waits.
   * Starts a new chat unless `sameChat`.
   */
  async function askForToolCall(
    page: Page,
    { sameChat = false, answers = true, slowSibling = false } = {}
  ): Promise<{ nonce: string; answer: string; conversation: string }> {
    const nonce = mockLlmNonce();
    const callId = `call-${nonce}`;
    const answer = `Finished ${nonce}`;
    const conversation = `approval-${nonce}`;
    const gatedCall = {
      id: callId,
      name: qualifiedToolName,
      arguments: { name: nonce },
    };
    await addMockLlmConversation({
      name: conversation,
      conditions: { prompt_contains: [nonce] },
      replies: [
        // Code mode calls the tools from an execute_code program.
        slowSibling
          ? mockLlmToolCallReply(
              [
                gatedCall,
                {
                  id: `slow-${nonce}`,
                  name: qualifiedSlowToolName,
                  arguments: { seconds: 60 },
                },
              ],
              { concurrent: true }
            )
          : mockLlmToolCallReply([gatedCall]),
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

  /**
   * Script a turn that starts a background agent whose tool call asks for
   * approval. The reply ends at once; the agent reports after the decision,
   * and its report wakes the chat with `followUp`. With `asksTwice`, the
   * agent calls the tool again, with `secondArgument`, after the first
   * result, and reports after the second.
   */
  async function startBackgroundAgent(
    page: Page,
    { asksTwice = false } = {}
  ): Promise<{ followUp: string; secondArgument: string }> {
    const nonce = mockLlmNonce();
    const task = `Greet ${nonce} in the background`;
    const callId = `agent-call-${nonce}`;
    const secondCallId = `agent-call-again-${nonce}`;
    const secondArgument = `again-${nonce}`;
    const report = `Mailer report ${nonce}`;
    const followUp = `The mailer reported ${nonce}`;
    await addMockLlmConversation({
      name: `root-${nonce}`,
      conditions: { prompt_contains: [`Start a mailer ${nonce}`] },
      replies: [
        {
          // Agent tools stay direct tools in code mode.
          tool_calls: [
            {
              id: `spawn-${nonce}`,
              name: "spawn_agent",
              arguments: { name: "mailer", instruction: task },
            },
          ],
          conditions: { offers: ["spawn_agent"] },
        },
        {
          text: `Started ${nonce}`,
          conditions: { has_results_for: [`spawn-${nonce}`] },
        },
        { text: followUp, conditions: { prompt_contains: [report] } },
      ],
    });
    const secondCall = mockLlmToolCallReply([
      {
        id: secondCallId,
        name: qualifiedToolName,
        arguments: { name: secondArgument },
      },
    ]);
    await addMockLlmConversation({
      name: `agent-${nonce}`,
      conditions: { prompt_contains: [task] },
      replies: [
        mockLlmToolCallReply([
          { id: callId, name: qualifiedToolName, arguments: { name: nonce } },
        ]),
        ...(asksTwice
          ? [
              {
                ...secondCall,
                conditions: {
                  ...secondCall.conditions,
                  has_results_for: [callId],
                },
              },
              { text: report, conditions: { has_results_for: [secondCallId] } },
            ]
          : [{ text: report, conditions: { has_results_for: [callId] } }]),
      ],
    });
    const chat = new ChatPage(page);
    await chat.gotoAgent(agentId, agentName);
    await chat.inputBar.fill(`Start a mailer ${nonce}`);
    await chat.inputBar.send();
    return { followUp, secondArgument };
  }

  test("Approve runs the tool and the answer continues", async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const { nonce, answer } = await askForToolCall(page);

    const card = new ToolApprovalCard(page);
    await card.expectPending(toolDisplayName);
    await card.expectArgument(nonce);
    const chat = new ChatPage(page);
    await chat.inputBar.expectAcceptsSend();

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

    await test.step("the reply continues in the same message", async () => {
      await card.expectApproved(toolDisplayName);
      await chat.expectLatestReplyComplete();
      await expect(chat.answerText(answer)).toBeVisible();
      await expect(chat.aiMessages).toHaveCount(1);
      await chat.expectCustomToolResult(toolDisplayName, TOOL_OUTPUT);
      await card.expectApproved(toolDisplayName);
    });

    await chat.reload();
    await card.expectApproved(toolDisplayName);
  });

  test("Reject skips the tool and the answer continues", async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const { answer, conversation } = await askForToolCall(page);

    const card = new ToolApprovalCard(page);
    await card.expectPending(toolDisplayName);
    await card.reject();

    await card.expectNotApproved(toolDisplayName);
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
    await card.expectApprovedForChat(toolDisplayName);
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

  test("A waiting card survives a reload while its turn is suspended", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const { answer } = await askForToolCall(page);

    const card = new ToolApprovalCard(page);
    await card.expectPending(toolDisplayName);
    const chat = new ChatPage(page);
    await chat.inputBar.expectAcceptsSend();
    await chat.reload();

    // The saved response replays the request; no stream runs.
    await card.expectPending(toolDisplayName);
    await card.expectPendingInView();
    await chat.inputBar.expectAcceptsSend();
    await card.approve();
    await card.expectApproved(toolDisplayName);
    await chat.expectLatestReplyComplete();
    await expect(chat.answerText(answer)).toBeVisible();
    await expect(chat.aiMessages).toHaveCount(1);
    await chat.expectCustomToolResult(toolDisplayName, TOOL_OUTPUT);
  });

  test("A background agent's card waits after the last message and does not block sends", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const { followUp } = await startBackgroundAgent(page);
    const chat = new ChatPage(page);

    const card = new ToolApprovalCard(page);
    await card.expectPending(toolDisplayName);
    await card.expectAgentRequest("mailer", toolDisplayName);
    await card.expectPendingInView();
    await chat.inputBar.expectAcceptsSend();

    await card.approve();
    // The agent continues in the background; its result wakes the chat.
    await expect(chat.answerText(followUp, 1)).toBeVisible({
      timeout: 60_000,
    });
    await card.expectApproved(toolDisplayName);
    await chat.reload();
    await card.expectApproved(toolDisplayName);
  });

  test("A background agent's card stays actionable after a reload and does not block sends", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const { followUp } = await startBackgroundAgent(page);
    const chat = new ChatPage(page);
    const card = new ToolApprovalCard(page);
    await card.expectPending(toolDisplayName);
    await chat.expectLatestReplyComplete();

    // The session load replays the agent's waiting request.
    await chat.reload();
    await card.expectPending(toolDisplayName);
    await card.expectAgentRequest("mailer", toolDisplayName);

    await test.step("a send runs while the agent's card waits", async () => {
      const nonce = mockLlmNonce();
      await addMockLlmConversation({
        name: `beside-agent-${nonce}`,
        conditions: { prompt_contains: [nonce] },
        replies: [{ text: `Hello beside ${nonce}` }],
      });
      await chat.inputBar.fill(`Say hello ${nonce}`);
      await chat.inputBar.send();
      await chat.expectLatestReplyComplete();
      await expect(chat.answerText(`Hello beside ${nonce}`, 1)).toBeVisible();
      await card.expectPending(toolDisplayName);
    });

    await card.approve();
    await expect(chat.answerText(followUp, 2)).toBeVisible({
      timeout: 60_000,
    });
    await card.expectApproved(toolDisplayName);
  });

  test("A background agent that asks again after a decision shows its next card without a reload", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const { followUp, secondArgument } = await startBackgroundAgent(page, {
      asksTwice: true,
    });
    const chat = new ChatPage(page);
    const card = new ToolApprovalCard(page);
    await card.expectPending(toolDisplayName);
    await chat.expectLatestReplyComplete();

    // The decision starts no stream; the chat reads its status until the
    // resumed agent parks on its next request.
    await card.approve();
    await card.expectArgument(secondArgument, 60_000);
    await card.expectPending(toolDisplayName);

    await card.approve();
    await expect(chat.answerText(followUp, 1)).toBeVisible({
      timeout: 60_000,
    });
    await card.expectApproved(toolDisplayName);
  });

  test("Always allow on the integration page runs later calls without a card", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const integrationPage = new CustomizeIntegrationPage(page);
    await integrationPage.goto(integrationId, "Actions");
    await integrationPage.setAlwaysAllow(toolDisplayName, true);

    try {
      const { answer, conversation } = await askForToolCall(page);
      const chat = new ChatPage(page);
      await chat.expectLatestReplyComplete();
      await expect(chat.answerText(answer)).toBeVisible();
      await expect(new ToolApprovalCard(page).cards).toHaveCount(0);
      const requests = await getMockLlmConversationRequests(conversation);
      expect(
        requests
          .flatMap((request) => request.messages)
          .some(
            (message) =>
              message.role === "tool" && message.content.includes(TOOL_OUTPUT)
          )
      ).toBe(true);
    } finally {
      await integrationPage.goto(integrationId, "Actions");
      await integrationPage.setAlwaysAllow(toolDisplayName, false);
    }
  });

  // Stop shows only while the turn is live. A lone gated call suspends the turn
  // as soon as its card opens, so the slow tool runs beside it.
  test("Stop during a live turn rejects its open card and the chat takes new messages", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await askForToolCall(page, { answers: false, slowSibling: true });

    const card = new ToolApprovalCard(page);
    await card.expectPending(toolDisplayName);
    const chat = new ChatPage(page);
    await chat.stop();
    await card.expectNotApproved(toolDisplayName, 30_000);
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

    // The stopped answer has settled; its record stays, also after a reload.
    await card.expectNotApproved(toolDisplayName);
    await chat.reload();
    await card.expectNotApproved(toolDisplayName);
  });
});
