import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs, loginAsRandomUser } from "../utils/auth";
import { sendMessage, verifyCurrentModel } from "../utils/chatActions";
import { OnyxApiClient } from "../utils/onyxApiClient";

type ModelConfiguration = {
  name: string;
  is_visible: boolean;
  display_name?: string;
};

type LlmProviderDescriptor = {
  name: string;
  provider: string;
  provider_display_name?: string;
  default_model_name: string;
  is_default_provider: boolean | null;
  model_configurations: ModelConfiguration[];
};

type SendChatMessagePayload = {
  chat_session_id: string;
  llm_override: {
    model_provider?: string;
    model_version?: string;
    temperature?: number;
  } | null;
};

type VisibleRuntimeModel = {
  displayName: string;
  modelName: string;
  providerName: string;
  providerType: string;
};

const SEND_CHAT_MESSAGE_API = "/api/chat/send-chat-message";

function uniqueName(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function getVisibleRuntimeModels(
  providers: LlmProviderDescriptor[]
): VisibleRuntimeModel[] {
  const models: VisibleRuntimeModel[] = [];

  for (const provider of providers) {
    for (const modelConfiguration of provider.model_configurations) {
      if (!modelConfiguration.is_visible) {
        continue;
      }
      models.push({
        displayName: modelConfiguration.display_name ?? modelConfiguration.name,
        modelName: modelConfiguration.name,
        providerName: provider.name,
        providerType: provider.provider,
      });
    }
  }

  return models;
}

function getUniqueDisplayNames(providers: LlmProviderDescriptor[]): string[] {
  const counts = new Map<string, number>();
  for (const model of getVisibleRuntimeModels(providers)) {
    counts.set(model.displayName, (counts.get(model.displayName) ?? 0) + 1);
  }

  return Array.from(counts.entries())
    .filter(([, count]) => count === 1)
    .map(([displayName]) => displayName)
    .sort((a, b) => a.localeCompare(b));
}

async function listRuntimeProviders(
  page: Page
): Promise<LlmProviderDescriptor[]> {
  const personaScopedResponse = await page.request.get(
    "/api/llm/persona/0/providers"
  );
  if (personaScopedResponse.ok()) {
    return (await personaScopedResponse.json()) as LlmProviderDescriptor[];
  }

  const response = await page.request.get("/api/llm/provider");
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as LlmProviderDescriptor[];
}

async function selectModelByDisplayName(
  page: Page,
  modelDisplayName: string
): Promise<void> {
  await page.getByTestId("ChatInputBar/llm-popover-trigger").click();
  const dialog = page.locator('[role="dialog"]');
  await expect(dialog).toBeVisible({ timeout: 10000 });

  await dialog.getByPlaceholder("Search models...").fill(modelDisplayName);

  const option = dialog.locator("button").filter({ hasText: modelDisplayName });
  await expect(option.first()).toBeVisible({ timeout: 10000 });
  await option.first().click();
  await expect(dialog).toBeHidden({ timeout: 10000 });
}

async function sendMessageAndCapturePayload(
  page: Page,
  message: string
): Promise<SendChatMessagePayload> {
  const requestPromise = page.waitForRequest(
    (request) =>
      request.url().includes(SEND_CHAT_MESSAGE_API) &&
      request.method() === "POST"
  );
  await sendMessage(page, message);
  const request = await requestPromise;
  return request.postDataJSON() as SendChatMessagePayload;
}

test.describe("LLM Runtime Selection", () => {
  test("model selection persists for the same chat session across messages and refresh", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    await page.goto("/app");
    await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 10000 });

    const providers = await listRuntimeProviders(page);
    const uniqueDisplayNames = getUniqueDisplayNames(providers);

    if (uniqueDisplayNames.length < 2) {
      test.skip(
        true,
        "Need at least 2 uniquely labeled visible models for runtime selection test"
      );
    }

    const currentModelLabel =
      (await page
        .getByTestId("ChatInputBar/llm-popover-trigger")
        .textContent()) ?? "";
    const selectedDisplayName =
      uniqueDisplayNames.find((name) => !currentModelLabel.includes(name)) ??
      uniqueDisplayNames[0]!;

    await selectModelByDisplayName(page, selectedDisplayName);
    await verifyCurrentModel(page, selectedDisplayName);

    const firstPayload = await sendMessageAndCapturePayload(
      page,
      "runtime-selection persistence message 1"
    );
    expect(firstPayload.llm_override?.model_version).toBeTruthy();
    expect(firstPayload.llm_override?.model_provider).toBeTruthy();

    const secondPayload = await sendMessageAndCapturePayload(
      page,
      "runtime-selection persistence message 2"
    );
    expect(secondPayload.chat_session_id).toBe(firstPayload.chat_session_id);
    expect(secondPayload.llm_override?.model_version).toBe(
      firstPayload.llm_override?.model_version
    );
    expect(secondPayload.llm_override?.model_provider).toBe(
      firstPayload.llm_override?.model_provider
    );

    const chatSessionResponse = await page.request.get(
      `/api/chat/get-chat-session/${firstPayload.chat_session_id}`
    );
    expect(chatSessionResponse.ok()).toBeTruthy();
    const chatSession = (await chatSessionResponse.json()) as {
      current_alternate_model?: string;
    };
    expect(chatSession.current_alternate_model ?? "").toContain(
      firstPayload.llm_override?.model_version ?? ""
    );

    await page.reload();
    await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 10000 });
    await verifyCurrentModel(page, selectedDisplayName);

    const thirdPayload = await sendMessageAndCapturePayload(
      page,
      "runtime-selection persistence message 3"
    );
    expect(thirdPayload.chat_session_id).toBe(firstPayload.chat_session_id);
    expect(thirdPayload.llm_override?.model_version).toBe(
      firstPayload.llm_override?.model_version
    );
    expect(thirdPayload.llm_override?.model_provider).toBe(
      firstPayload.llm_override?.model_provider
    );
  });

  test("regenerate with an alternate model preserves version history and sends alternate override", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAsRandomUser(page);
    await page.goto("/app");
    await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 10000 });

    const providers = await listRuntimeProviders(page);
    const visibleModels = getVisibleRuntimeModels(providers);
    const uniqueDisplayNames = getUniqueDisplayNames(providers);

    if (uniqueDisplayNames.length < 2) {
      test.skip(
        true,
        "Need at least 2 uniquely labeled visible models for regeneration model switch"
      );
    }

    const initialModelDisplayName = uniqueDisplayNames[0]!;
    const regenerateModelDisplayName = uniqueDisplayNames[1]!;

    const initialModel = visibleModels.find(
      (model) => model.displayName === initialModelDisplayName
    );
    const regenerateModel = visibleModels.find(
      (model) => model.displayName === regenerateModelDisplayName
    );
    expect(initialModel).toBeTruthy();
    expect(regenerateModel).toBeTruthy();

    await selectModelByDisplayName(page, initialModelDisplayName);
    await verifyCurrentModel(page, initialModelDisplayName);

    const initialPayload = await sendMessageAndCapturePayload(
      page,
      "Runtime selection regeneration seed"
    );
    expect(initialPayload.llm_override?.model_version).toBe(
      initialModel!.modelName
    );

    const aiMessage = page.locator('[data-testid="onyx-ai-message"]').first();
    await aiMessage.hover();
    await aiMessage.getByTestId("AgentMessage/regenerate").click();

    const regenerateDialog = page.locator('[role="dialog"]');
    await expect(regenerateDialog).toBeVisible({ timeout: 10000 });
    await regenerateDialog
      .getByPlaceholder("Search models...")
      .fill(regenerateModelDisplayName);

    const regenerationRequestPromise = page.waitForRequest(
      (request) =>
        request.url().includes(SEND_CHAT_MESSAGE_API) &&
        request.method() === "POST"
    );
    await regenerateDialog
      .locator("button")
      .filter({ hasText: regenerateModelDisplayName })
      .first()
      .click();

    const regenerationRequest = await regenerationRequestPromise;
    const regenerationPayload =
      regenerationRequest.postDataJSON() as SendChatMessagePayload;

    expect(regenerationPayload.chat_session_id).toBe(
      initialPayload.chat_session_id
    );
    expect(regenerationPayload.llm_override?.model_version).toBe(
      regenerateModel!.modelName
    );
    expect(regenerationPayload.llm_override?.model_provider).toBe(
      regenerateModel!.providerName
    );
    expect(regenerationPayload.llm_override?.model_version).not.toBe(
      initialPayload.llm_override?.model_version
    );

    const messageSwitcher = page
      .getByTestId("MessageSwitcher/container")
      .first();
    await expect(messageSwitcher).toBeVisible({ timeout: 20000 });
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
  });

  test("same model name across providers respects provider-specific model descriptor", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const sharedModelName = "shared-runtime-model";
    const sharedDisplayName = "Shared Runtime Model";
    const openAiProviderName = "PW Shared OpenAI";
    const anthropicProviderName = "PW Shared Anthropic";

    const mockedProviders: LlmProviderDescriptor[] = [
      {
        name: openAiProviderName,
        provider: "openai",
        provider_display_name: "OpenAI",
        default_model_name: sharedModelName,
        is_default_provider: true,
        model_configurations: [
          {
            name: sharedModelName,
            display_name: sharedDisplayName,
            is_visible: true,
          },
        ],
      },
      {
        name: anthropicProviderName,
        provider: "anthropic",
        provider_display_name: "Anthropic",
        default_model_name: sharedModelName,
        is_default_provider: false,
        model_configurations: [
          {
            name: sharedModelName,
            display_name: sharedDisplayName,
            is_visible: true,
          },
        ],
      },
    ];

    await page.route("**/api/llm/provider", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockedProviders),
      });
    });
    await page.route("**/api/llm/persona/*/providers", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockedProviders),
      });
    });

    const createSessionResponse = await page.request.post(
      "/api/chat/create-chat-session",
      {
        data: {
          persona_id: 0,
          description: uniqueName("runtime-provider-resolution"),
          project_id: null,
        },
      }
    );
    expect(createSessionResponse.ok()).toBeTruthy();
    const createSessionData = (await createSessionResponse.json()) as {
      chat_session_id: string;
    };
    const chatSessionId = createSessionData.chat_session_id;

    const setModelResponse = await page.request.put(
      "/api/chat/update-chat-session-model",
      {
        data: {
          chat_session_id: chatSessionId,
          new_alternate_model: `${anthropicProviderName}__anthropic__${sharedModelName}`,
        },
      }
    );
    expect(setModelResponse.ok()).toBeTruthy();

    await page.goto(`/app?chatId=${chatSessionId}`);
    await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 10000 });
    await verifyCurrentModel(page, sharedDisplayName);

    const sendRequestPromise = page.waitForRequest(
      (request) =>
        request.url().includes(SEND_CHAT_MESSAGE_API) &&
        request.method() === "POST"
    );
    await page.locator("#onyx-chat-input-textarea").fill("provider resolution");
    await page.locator("#onyx-chat-input-send-button").click();

    const sendRequest = await sendRequestPromise;
    const payload = sendRequest.postDataJSON() as SendChatMessagePayload;
    expect(payload.chat_session_id).toBe(chatSessionId);
    expect(payload.llm_override?.model_version).toBe(sharedModelName);
    expect(payload.llm_override?.model_provider).toBe(anthropicProviderName);

    const apiClient = new OnyxApiClient(page.request);
    await apiClient.deleteChatSession(chatSessionId);
  });

  test("restricted provider is unavailable to unauthorized user during runtime selection", async ({
    page,
  }) => {
    let groupId: number | null = null;
    let restrictedProviderId: number | null = null;
    const restrictedProviderName = uniqueName("PW Restricted Runtime Provider");
    const restrictedGroupName = uniqueName("PW Runtime Restricted Group");

    const apiClient = new OnyxApiClient(page.request);

    try {
      await page.context().clearCookies();
      await loginAs(page, "admin");
      groupId = await apiClient.createUserGroup(restrictedGroupName);
      restrictedProviderId = await apiClient.createRestrictedProvider(
        restrictedProviderName,
        groupId
      );

      await page.context().clearCookies();
      await loginAsRandomUser(page);

      const providers = await listRuntimeProviders(page);
      expect(
        providers.some((provider) => provider.name === restrictedProviderName)
      ).toBe(false);

      await page.goto("/app");
      await page.waitForSelector("#onyx-chat-input-textarea", {
        timeout: 10000,
      });

      const payload = await sendMessageAndCapturePayload(
        page,
        "rbac runtime selection validation"
      );
      expect(payload.llm_override?.model_provider).not.toBe(
        restrictedProviderName
      );
    } finally {
      await page.context().clearCookies();
      await loginAs(page, "admin");

      if (restrictedProviderId) {
        await apiClient.deleteProvider(restrictedProviderId);
      }
      if (groupId) {
        await apiClient.deleteUserGroup(groupId);
      }
    }
  });
});
