import { expect, Page, test } from "@playwright/test";
import { loginAs } from "../utils/auth";
import {
  selectModelFromInputPopover,
  sendMessage,
  startNewChat,
  verifyCurrentModel,
} from "../utils/chatActions";
import { OnyxApiClient } from "../utils/onyxApiClient";

type SendChatMessagePayload = {
  llm_override?: {
    model_provider?: string | null;
    model_version?: string | null;
    temperature?: number | null;
  } | null;
};

function uniqueName(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function openChat(page: Page): Promise<void> {
  await page.goto("/app");
  await page.waitForLoadState("networkidle");
  await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 15000 });
}

async function loginWithCleanCookies(
  page: Page,
  user: "admin" | "user"
): Promise<void> {
  await page.context().clearCookies();
  await loginAs(page, user);
}

async function createLlmProvider(
  page: Page,
  params: {
    name: string;
    provider: string;
    defaultModelName: string;
    isPublic: boolean;
    groupIds?: number[];
  }
): Promise<number> {
  const response = await page.request.put(
    "/api/admin/llm/provider?is_creation=true",
    {
      data: {
        name: params.name,
        provider: params.provider,
        api_key: "e2e-placeholder-api-key-not-used",
        default_model_name: params.defaultModelName,
        is_public: params.isPublic,
        groups: params.groupIds ?? [],
        personas: [],
        model_configurations: [
          {
            name: params.defaultModelName,
            is_visible: true,
          },
        ],
      },
    }
  );

  expect(response.ok()).toBeTruthy();
  const data = (await response.json()) as { id: number };
  return data.id;
}

async function sendMessageAndCapturePayload(
  page: Page,
  message: string
): Promise<SendChatMessagePayload> {
  const requestPromise = page.waitForRequest(
    (request) =>
      request.url().includes("/api/chat/send-chat-message") &&
      request.method() === "POST"
  );

  await sendMessage(page, message);

  const request = await requestPromise;
  return request.postDataJSON() as SendChatMessagePayload;
}

type LlmProviderBasics = {
  name: string;
  model_configurations: Array<{ name: string }>;
};

async function listUserLlmProviders(page: Page): Promise<LlmProviderBasics[]> {
  const response = await page.request.get("/api/llm/provider");
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as LlmProviderBasics[];
}

async function waitForModelOnProvider(
  page: Page,
  modelName: string,
  providerNames: string[]
): Promise<void> {
  await expect
    .poll(
      async () => {
        const providers = await listUserLlmProviders(page);
        return providerNames.every((providerName) =>
          providers.some(
            (provider) =>
              provider.name === providerName &&
              provider.model_configurations.some(
                (modelConfig) => modelConfig.name === modelName
              )
          )
        );
      },
      { timeout: 30000 }
    )
    .toBeTruthy();
}

function buildMockStreamResponse(turn: number): string {
  const userMessageId = turn * 100 + 1;
  const assistantMessageId = turn * 100 + 2;

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
        content: "Mock response for provider collision assertion.",
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

  return `${packets.map((packet) => JSON.stringify(packet)).join("\n")}\n`;
}

test.describe("LLM Runtime Selection", () => {
  let providersToCleanup: number[] = [];
  let groupsToCleanup: number[] = [];

  test.beforeEach(async ({ page }) => {
    providersToCleanup = [];
    groupsToCleanup = [];
    await loginWithCleanCookies(page, "user");
  });

  test.afterEach(async ({ page }) => {
    await loginWithCleanCookies(page, "admin");

    const client = new OnyxApiClient(page.request);
    const providerIds = Array.from(new Set(providersToCleanup));
    const groupIds = Array.from(new Set(groupsToCleanup));

    for (const providerId of providerIds) {
      try {
        await client.deleteProvider(providerId);
      } catch (error) {
        console.warn(
          `Cleanup failed for provider ${providerId}: ${String(error)}`
        );
      }
    }

    for (const groupId of groupIds) {
      try {
        await client.deleteUserGroup(groupId);
      } catch (error) {
        console.warn(`Cleanup failed for group ${groupId}: ${String(error)}`);
      }
    }
  });

  test("model selection persists across refresh and subsequent messages in the same chat", async ({
    page,
  }) => {
    await loginWithCleanCookies(page, "admin");

    const persistenceProviderName = uniqueName("PW Runtime Persist Provider");
    const persistenceModelName = `persist-runtime-model-${Date.now()}`;
    const persistenceProviderId = await createLlmProvider(page, {
      name: persistenceProviderName,
      provider: "openai",
      defaultModelName: persistenceModelName,
      isPublic: true,
    });
    providersToCleanup.push(persistenceProviderId);
    await waitForModelOnProvider(page, persistenceModelName, [
      persistenceProviderName,
    ]);

    await loginWithCleanCookies(page, "user");
    await openChat(page);

    let turn = 0;
    await page.route("**/api/chat/send-chat-message", async (route) => {
      turn += 1;
      await route.fulfill({
        status: 200,
        contentType: "text/plain",
        body: buildMockStreamResponse(turn),
      });
    });

    const selectedModelDisplay = await selectModelFromInputPopover(page, [
      persistenceModelName,
    ]);
    await verifyCurrentModel(page, selectedModelDisplay);

    const firstPayload = await sendMessageAndCapturePayload(
      page,
      "First persistence check message."
    );
    const firstModelVersion = firstPayload.llm_override?.model_version;
    const firstModelProvider = firstPayload.llm_override?.model_provider;

    expect(firstModelVersion).toBeTruthy();
    expect(firstModelProvider).toBeTruthy();
    expect(firstModelProvider).toBe(persistenceProviderName);
    expect(page.url()).toContain("chatId=");

    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 15000 });

    await verifyCurrentModel(page, selectedModelDisplay);

    const secondPayload = await sendMessageAndCapturePayload(
      page,
      "Second persistence check after refresh."
    );

    expect(secondPayload.llm_override?.model_version).toBe(firstModelVersion);
    expect(secondPayload.llm_override?.model_provider).toBe(firstModelProvider);
  });

  test("regenerate with alternate model preserves version history semantics", async ({
    page,
  }) => {
    await openChat(page);

    let turn = 0;
    await page.route("**/api/chat/send-chat-message", async (route) => {
      turn += 1;
      await route.fulfill({
        status: 200,
        contentType: "text/plain",
        body: buildMockStreamResponse(turn),
      });
    });

    // Keep this aligned with the existing stable regenerate flow test.
    const initialModelDisplay = await selectModelFromInputPopover(page, [
      "GPT-4.1",
      "GPT-4o Mini",
      "GPT-4o",
    ]);
    await verifyCurrentModel(page, initialModelDisplay);

    const initialPayload = await sendMessageAndCapturePayload(
      page,
      "Generate a short sentence for regeneration."
    );
    const initialModelVersion = initialPayload.llm_override?.model_version;

    const aiMessage = page.locator('[data-testid="onyx-ai-message"]').first();
    await aiMessage.hover();

    const regenerateControl = aiMessage.getByTestId("AgentMessage/regenerate");
    await regenerateControl.click();
    await page.waitForSelector('[role="dialog"]', {
      state: "visible",
      timeout: 10000,
    });

    const regenerateDialog = page.locator('[role="dialog"]');
    const alternateModelOption = regenerateDialog
      .locator('button[data-selected="false"]')
      .first();

    test.skip(
      (await regenerateDialog
        .locator('button[data-selected="false"]')
        .count()) === 0,
      "Regenerate model picker requires at least two runtime model options"
    );

    const regenerateRequestPromise = page.waitForRequest(
      (request) =>
        request.url().includes("/api/chat/send-chat-message") &&
        request.method() === "POST"
    );

    await expect(alternateModelOption).toBeVisible({ timeout: 15000 });
    await alternateModelOption.click();

    const regeneratePayload = (await regenerateRequestPromise.then((request) =>
      request.postDataJSON()
    )) as SendChatMessagePayload;

    await page.waitForSelector('[data-testid="AgentMessage/regenerate"]', {
      state: "visible",
      timeout: 20000,
    });

    const messageSwitcher = page
      .getByTestId("MessageSwitcher/container")
      .first();
    await expect(messageSwitcher).toBeVisible({ timeout: 10000 });
    await expect(messageSwitcher).toContainText("2/2");

    await messageSwitcher
      .locator("..")
      .locator("svg")
      .first()
      .locator("..")
      .click();
    await expect(messageSwitcher).toContainText("1/2");

    await messageSwitcher
      .locator("..")
      .locator("svg")
      .last()
      .locator("..")
      .click();
    await expect(messageSwitcher).toContainText("2/2");

    expect(regeneratePayload.llm_override?.model_version).toBeTruthy();
    expect(regeneratePayload.llm_override?.model_provider).toBeTruthy();
    expect(regeneratePayload.llm_override?.model_version).not.toBe(
      initialModelVersion
    );
  });

  test("same model name across providers resolves to provider-specific runtime payloads", async ({
    page,
  }) => {
    await loginWithCleanCookies(page, "admin");

    const sharedModelName = `shared-runtime-model-${Date.now()}`;
    const openAiProviderName = uniqueName("PW Runtime OpenAI");
    const anthropicProviderName = uniqueName("PW Runtime Anthropic");

    const openAiProviderId = await createLlmProvider(page, {
      name: openAiProviderName,
      provider: "openai",
      defaultModelName: sharedModelName,
      isPublic: true,
    });
    const anthropicProviderId = await createLlmProvider(page, {
      name: anthropicProviderName,
      provider: "anthropic",
      defaultModelName: sharedModelName,
      isPublic: true,
    });

    providersToCleanup.push(openAiProviderId, anthropicProviderId);

    await waitForModelOnProvider(page, sharedModelName, [
      openAiProviderName,
      anthropicProviderName,
    ]);

    await loginWithCleanCookies(page, "user");

    const capturedPayloads: SendChatMessagePayload[] = [];
    let turn = 0;

    await page.route("**/api/chat/send-chat-message", async (route) => {
      turn += 1;
      capturedPayloads.push(
        route.request().postDataJSON() as SendChatMessagePayload
      );
      await route.fulfill({
        status: 200,
        contentType: "text/plain",
        body: buildMockStreamResponse(turn),
      });
    });

    await openChat(page);

    await page.getByTestId("AppInputBar/llm-popover-trigger").click();
    await page.waitForSelector('[role="dialog"]', { state: "visible" });
    const dialog = page.locator('[role="dialog"]');
    await dialog.getByPlaceholder("Search models...").fill(sharedModelName);

    const sharedModelOptions = dialog.locator("button[data-selected]");
    await expect(sharedModelOptions).toHaveCount(2);
    const openAiModelOption = dialog
      .getByRole("region", { name: /openai/i })
      .locator("button[data-selected]")
      .first();
    await expect(openAiModelOption).toBeVisible();
    await openAiModelOption.click();
    await page.waitForSelector('[role="dialog"]', { state: "hidden" });

    await sendMessage(page, "Collision payload check one.");
    await expect.poll(() => capturedPayloads.length).toBe(1);

    // Use a new session so runtime selection is not overwritten by the previous
    // chat session's persisted model override.
    await startNewChat(page);
    await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 15000 });

    await page.getByTestId("AppInputBar/llm-popover-trigger").click();
    await page.waitForSelector('[role="dialog"]', { state: "visible" });
    const secondDialog = page.locator('[role="dialog"]');
    await secondDialog
      .getByPlaceholder("Search models...")
      .fill(sharedModelName);

    const secondSharedModelOptions = secondDialog.locator(
      "button[data-selected]"
    );
    await expect(secondSharedModelOptions).toHaveCount(2);
    const anthropicModelOption = secondDialog
      .getByRole("region", { name: /anthropic/i })
      .locator("button[data-selected]")
      .first();
    await expect(anthropicModelOption).toBeVisible();
    await anthropicModelOption.click();
    await page.waitForSelector('[role="dialog"]', { state: "hidden" });

    await page.getByTestId("AppInputBar/llm-popover-trigger").click();
    await page.waitForSelector('[role="dialog"]', { state: "visible" });
    const verifyDialog = page.locator('[role="dialog"]');
    const selectedAnthropicOption = verifyDialog
      .getByRole("region", { name: /anthropic/i })
      .locator('button[data-selected="true"]');
    await expect(selectedAnthropicOption).toHaveCount(1);
    await page.keyboard.press("Escape");
    await page.waitForSelector('[role="dialog"]', { state: "hidden" });

    await sendMessage(page, "Collision payload check two.");
    await expect.poll(() => capturedPayloads.length).toBe(2);

    for (const payload of capturedPayloads) {
      expect(payload.llm_override?.model_version).toBe(sharedModelName);
      expect(payload.llm_override?.model_provider).toBeTruthy();
    }

    const providersUsed = capturedPayloads.map(
      (payload) => payload.llm_override?.model_provider
    );

    expect(new Set(providersUsed)).toEqual(
      new Set([openAiProviderName, anthropicProviderName])
    );
  });

  test("restricted provider model is unavailable to unauthorized runtime user selection", async ({
    page,
  }) => {
    await loginWithCleanCookies(page, "admin");

    const client = new OnyxApiClient(page.request);
    const restrictedGroupName = uniqueName("PW Runtime Restricted Group");
    const restrictedModelName = `restricted-runtime-model-${Date.now()}`;
    const restrictedProviderName = uniqueName("PW Runtime Restricted Provider");

    let groupId: number;
    try {
      groupId = await client.createUserGroup(restrictedGroupName);
    } catch (error) {
      const errorText = String(error);
      const requiresEnterpriseLicense =
        errorText.includes("enterprise_license_required") ||
        errorText.includes("This feature requires an Enterprise license");
      test.skip(
        requiresEnterpriseLicense,
        "Restricted provider test requires Enterprise license-enabled environment"
      );
      throw error;
    }
    groupsToCleanup.push(groupId);

    const restrictedProviderId = await createLlmProvider(page, {
      name: restrictedProviderName,
      provider: "openai",
      defaultModelName: restrictedModelName,
      isPublic: false,
      groupIds: [groupId],
    });
    providersToCleanup.push(restrictedProviderId);

    await loginWithCleanCookies(page, "user");
    await openChat(page);

    await page.getByTestId("AppInputBar/llm-popover-trigger").click();
    await page.waitForSelector('[role="dialog"]', { state: "visible" });

    const dialog = page.locator('[role="dialog"]');
    await dialog.getByPlaceholder("Search models...").fill(restrictedModelName);

    const restrictedModelOption = dialog
      .locator("button[data-selected]")
      .filter({ hasText: restrictedModelName });

    await expect(restrictedModelOption).toHaveCount(0);
    await expect(dialog.getByText("No models found")).toBeVisible();
  });
});
