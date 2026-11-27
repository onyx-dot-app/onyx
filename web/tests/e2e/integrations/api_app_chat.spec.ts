import { expect, test, type Page } from "@playwright/test";
import { apiLogin } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  addMockLlmConversation,
  mockLlmNonce,
  mockLlmToolCallReply,
} from "@tests/e2e/utils/mockLlm";
import {
  ApiAppUpstream,
  TICKET_ACTIONS,
  ticketsOpenApiSpec,
} from "@tests/e2e/utils/apiAppUpstream";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { ToolApprovalCard } from "@tests/e2e/pages/ToolApprovalCard";
import { CustomizeIntegrationPage } from "@tests/e2e/pages/CustomizeIntegrationPage";

const MEMBER_KEY = "pw-member-ticket-key";

/**
 * A member connects a REST app with their own API key and uses its actions
 * in chat. The read action is on Allow and runs at once; the create action
 * is on Ask and runs only after the member approves it. Each call that runs
 * reaches the upstream API with the member's key.
 */
test.describe("REST app actions in chat @code-mode", () => {
  test.describe.configure({ mode: "serial" });

  const suffix = Date.now();
  const appName = `PW Ticket App ${suffix}`;
  const agentName = `PW Ticket Agent ${suffix}`;
  const member = {
    email: `pw-api-app-chat-${suffix}@example.com`,
    password: "TestPassword123!",
  };
  let upstream: ApiAppUpstream;
  let integrationId: number | null = null;
  let agentId: number | null = null;

  test.beforeAll(async ({ browser }) => {
    upstream = await ApiAppUpstream.start();
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const admin = new OnyxApiClient(context.request);
      const created = await admin.createIntegration({
        for_organization: true,
        name: appName,
        description: "Ticket API (e2e)",
        auth_mode: "individual",
        auth_method: "api_key",
        credential_fields: [{ key: "api_key", label: "API Key", secret: true }],
        header_template: { Authorization: "Bearer {api_key}" },
        oauth_client: null,
        config: {
          shape: "openapi",
          openapi_document: JSON.stringify(
            ticketsOpenApiSpec(appName, upstream.apiBaseUrl)
          ),
        },
      });
      integrationId = created.id;
      agentId = await admin.createAgentWithIntegrations(
        agentName,
        [created.id],
        { isPublic: true }
      );
      await admin.registerUser(member.email, member.password);
    } finally {
      await context.close();
    }
  });

  test.afterAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const admin = new OnyxApiClient(context.request);
      if (agentId !== null) await admin.deleteAgent(agentId);
      if (integrationId !== null) await admin.deleteIntegration(integrationId);
    } finally {
      await context.close();
      await upstream.stop();
    }
  });

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await apiLogin(page, member.email, member.password);
  });

  /** Scripts a turn that calls one action, then answers once it has a
   * result, and sends it in a new chat with the agent. */
  async function callAction(
    page: Page,
    operationId: string,
    args: (nonce: string) => Record<string, unknown>
  ): Promise<{ nonce: string; answer: string }> {
    const nonce = mockLlmNonce();
    const callId = `call-${nonce}`;
    const answer = `Done ${nonce}`;
    await addMockLlmConversation({
      name: `api-app-${nonce}`,
      conditions: { prompt_contains: [nonce] },
      replies: [
        mockLlmToolCallReply([
          {
            id: callId,
            name: `custom__${integrationId}__${operationId}`,
            arguments: args(nonce),
          },
        ]),
        { text: answer, conditions: { has_results_for: [callId] } },
      ],
    });
    const chat = new ChatPage(page);
    await chat.gotoAgent(agentId!, agentName);
    await chat.inputBar.fill(`Use the ticket app ${nonce}`);
    await chat.inputBar.send();
    return { nonce, answer };
  }

  test("a member connects the app with their own key", async ({ page }) => {
    const detail = new CustomizeIntegrationPage(page);
    await detail.openApp();
    await detail.goto(integrationId!);
    await detail.expectStatus("Not connected");
    await detail.connectWithCredentials(appName, { "API Key": MEMBER_KEY });
    await detail.expectStatus("Connected");
  });

  test("an Allow action runs with the member's key", async ({ page }) => {
    const { nonce, answer } = await callAction(
      page,
      TICKET_ACTIONS.read.operationId,
      (id) => ({ id })
    );
    const chat = new ChatPage(page);
    await chat.expectLatestReplyComplete();
    await expect(chat.answerText(answer)).toBeVisible();
    await expect(new ToolApprovalCard(page).cards).toHaveCount(0);
    expect(upstream.apiRequestsWith(nonce)).toEqual([
      {
        method: "GET",
        path: `/api/tickets/${nonce}`,
        authorization: `Bearer ${MEMBER_KEY}`,
        body: "",
      },
    ]);
  });

  test("an Ask action runs after Approve once", async ({ page }) => {
    const { nonce, answer } = await callAction(
      page,
      TICKET_ACTIONS.create.operationId,
      (title) => ({ requestBody: { title } })
    );
    const headline = `${TICKET_ACTIONS.create.summary} in ${appName}`;
    const card = new ToolApprovalCard(page);
    await card.expectPending(headline);
    expect(upstream.apiRequestsWith(nonce)).toHaveLength(0);

    await card.approve();
    await card.expectApproved(headline);
    const chat = new ChatPage(page);
    await chat.expectLatestReplyComplete();
    await expect(chat.answerText(answer)).toBeVisible();
    const requests = upstream.apiRequestsWith(nonce);
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({
      method: "POST",
      path: "/api/tickets",
      authorization: `Bearer ${MEMBER_KEY}`,
    });
    expect(JSON.parse(requests[0]!.body)).toEqual({ title: nonce });
  });

  test("an Ask action does not run after Reject", async ({ page }) => {
    const { nonce, answer } = await callAction(
      page,
      TICKET_ACTIONS.create.operationId,
      (title) => ({ requestBody: { title } })
    );
    const headline = `${TICKET_ACTIONS.create.summary} in ${appName}`;
    const card = new ToolApprovalCard(page);
    await card.expectPending(headline);

    await card.reject();
    await card.expectNotApproved(headline);
    const chat = new ChatPage(page);
    await chat.expectLatestReplyComplete();
    await expect(chat.answerText(answer)).toBeVisible();
    expect(upstream.apiRequestsWith(nonce)).toHaveLength(0);
  });
});
