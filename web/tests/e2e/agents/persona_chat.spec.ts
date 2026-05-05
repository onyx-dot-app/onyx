import { test, expect, Browser } from "@playwright/test";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { CHECKERED_PNG } from "@tests/e2e/fixtures/images";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import {
  buildMockStream,
  mockChatEndpoint,
  resetTurnCounter,
} from "@tests/e2e/utils/chatMock";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const USER_MESSAGE = "Hi there";
const AI_RESPONSE = "Hello, I'm a custom persona!";

test.describe("Chatting with a custom persona", () => {
  test.describe.configure({ mode: "serial" });

  let agentId: number | null = null;
  const agentName = `E2E Persona Chat`;

  test.beforeAll(async ({ browser }: { browser: Browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const page = await context.newPage();

    const uploadResp = await page.request.post(
      "/api/admin/persona/upload-image",
      {
        multipart: {
          file: {
            name: "avatar.png",
            mimeType: "image/png",
            buffer: CHECKERED_PNG,
          },
        },
      }
    );
    expect(uploadResp.ok()).toBeTruthy();
    const { file_id: avatarFileId } = (await uploadResp.json()) as {
      file_id: string;
    };

    const createResp = await page.request.post("/api/persona", {
      data: {
        name: agentName,
        description: "Persona used for chat rendering tests.",
        document_set_ids: [],
        is_public: true,
        tool_ids: [],
        uploaded_image_id: avatarFileId,
        system_prompt: "",
        task_prompt: "",
        datetime_aware: true,
      },
    });
    expect(createResp.ok()).toBeTruthy();
    const persona = (await createResp.json()) as { id: number };
    agentId = persona.id;

    await context.close();
  });

  test.afterAll(async ({ browser }: { browser: Browser }) => {
    if (agentId === null) return;
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const page = await context.newPage();
    const cleanupClient = new OnyxApiClient(page.request);
    await cleanupClient.deleteAgent(agentId);
    await context.close();
  });

  test.beforeEach(() => {
    resetTurnCounter();
  });

  test("welcome page renders the selected persona", async ({ page }) => {
    expect(agentId).not.toBeNull();
    const chat = new ChatPage(page);

    await page.goto(`/app?agentId=${agentId}`);
    await chat.chatInputTextarea.waitFor({ state: "visible", timeout: 15000 });

    const nameDisplay = page.getByTestId("agent-name-display");
    await expect(nameDisplay).toBeVisible({ timeout: 10000 });
    await expect(nameDisplay).toContainText(agentName);

    await chat.screenshotContainer("persona-chat-welcome");
  });

  test("sends a message and renders the AI response", async ({ page }) => {
    expect(agentId).not.toBeNull();
    const chat = new ChatPage(page);

    await page.goto(`/app?agentId=${agentId}`);
    await chat.chatInputTextarea.waitFor({ state: "visible", timeout: 15000 });
    await mockChatEndpoint(page, buildMockStream(AI_RESPONSE));

    await sendMessage(page, USER_MESSAGE);

    const userMessage = chat.humanMessage(0);
    await expect(userMessage).toBeVisible();
    await expect(userMessage).toContainText(USER_MESSAGE);

    const aiMessage = chat.aiMessage(0);
    await expect(aiMessage).toBeVisible();
    await expect(aiMessage).toContainText(AI_RESPONSE);

    await chat.screenshotContainer("persona-chat-response");
  });
});
