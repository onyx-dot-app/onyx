import { test, expect, Page, Locator } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";

const VOICE_URL = "/admin/configuration/voice";

const FAKE_PROVIDERS = {
  openai_active_stt: {
    id: 1,
    name: "openai",
    provider_type: "openai",
    is_default_stt: true,
    is_default_tts: false,
    stt_model: "whisper",
    tts_model: null,
    default_voice: null,
    has_api_key: true,
    target_uri: null,
  },
  openai_active_both: {
    id: 1,
    name: "openai",
    provider_type: "openai",
    is_default_stt: true,
    is_default_tts: true,
    stt_model: "whisper",
    tts_model: "tts-1",
    default_voice: "alloy",
    has_api_key: true,
    target_uri: null,
  },
  openai_connected: {
    id: 1,
    name: "openai",
    provider_type: "openai",
    is_default_stt: false,
    is_default_tts: false,
    stt_model: null,
    tts_model: null,
    default_voice: null,
    has_api_key: true,
    target_uri: null,
  },
  elevenlabs_connected: {
    id: 2,
    name: "elevenlabs",
    provider_type: "elevenlabs",
    is_default_stt: false,
    is_default_tts: false,
    stt_model: null,
    tts_model: null,
    default_voice: null,
    has_api_key: true,
    target_uri: null,
  },
};

function findModelCard(page: Page, ariaLabel: string): Locator {
  return page.getByLabel(ariaLabel, { exact: true });
}

function mainContainer(page: Page): Locator {
  return page.locator("[data-main-container]");
}

async function mockVoiceApis(
  page: Page,
  providers: (typeof FAKE_PROVIDERS)[keyof typeof FAKE_PROVIDERS][]
) {
  await page.route("**/api/admin/voice/providers", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, json: providers });
    } else {
      await route.continue();
    }
  });
}

test.describe("Voice Provider Disconnect", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test("should disconnect a non-active provider and affect both STT and TTS cards", async ({
    page,
  }) => {
    const providers = [
      { ...FAKE_PROVIDERS.openai_connected },
      { ...FAKE_PROVIDERS.elevenlabs_connected },
    ];
    await mockVoiceApis(page, providers);

    await page.goto(VOICE_URL);
    await page.waitForSelector("text=Speech to Text", { timeout: 20000 });

    const whisperCard = findModelCard(page, "voice-stt-whisper");
    await whisperCard.waitFor({ state: "visible", timeout: 10000 });

    await expectElementScreenshot(mainContainer(page), {
      name: "voice-disconnect-non-active-before",
    });

    const disconnectButton = whisperCard.getByRole("button", {
      name: "Disconnect Whisper",
    });
    await expect(disconnectButton).toBeVisible();
    await expect(disconnectButton).toBeEnabled();

    // Mock DELETE to succeed and remove OpenAI from provider list
    await page.route("**/api/admin/voice/providers/1", async (route) => {
      if (route.request().method() === "DELETE") {
        await page.unroute("**/api/admin/voice/providers");
        await page.route("**/api/admin/voice/providers", async (route) => {
          if (route.request().method() === "GET") {
            await route.fulfill({
              status: 200,
              json: [{ ...FAKE_PROVIDERS.elevenlabs_connected }],
            });
          } else {
            await route.continue();
          }
        });
        await route.fulfill({ status: 200, json: {} });
      } else {
        await route.continue();
      }
    });

    await disconnectButton.click();

    // Modal shows provider name, not model name
    const confirmDialog = page.getByRole("dialog");
    await expect(confirmDialog).toBeVisible({ timeout: 5000 });
    await expect(confirmDialog).toContainText("Disconnect OpenAI");

    await expectElementScreenshot(confirmDialog, {
      name: "voice-disconnect-non-active-modal",
    });

    const confirmButton = confirmDialog.getByRole("button", {
      name: "Disconnect",
    });
    await confirmButton.click();

    // Both STT and TTS cards for OpenAI revert to disconnected
    await expect(
      whisperCard.getByRole("button", { name: "Connect" })
    ).toBeVisible({ timeout: 10000 });

    const tts1Card = findModelCard(page, "voice-tts-tts-1");
    await expect(tts1Card.getByRole("button", { name: "Connect" })).toBeVisible(
      { timeout: 10000 }
    );

    await expectElementScreenshot(mainContainer(page), {
      name: "voice-disconnect-non-active-after",
    });
  });

  test("should show replacement dropdown when disconnecting active provider with alternatives", async ({
    page,
  }) => {
    // OpenAI is active for STT, ElevenLabs is also configured
    const providers = [
      { ...FAKE_PROVIDERS.openai_active_stt },
      { ...FAKE_PROVIDERS.elevenlabs_connected },
    ];
    await mockVoiceApis(page, providers);

    await page.goto(VOICE_URL);
    await page.waitForSelector("text=Speech to Text", { timeout: 20000 });

    const whisperCard = findModelCard(page, "voice-stt-whisper");
    await whisperCard.waitFor({ state: "visible", timeout: 10000 });

    await expectElementScreenshot(mainContainer(page), {
      name: "voice-disconnect-active-with-alt-before",
    });

    const disconnectButton = whisperCard.getByRole("button", {
      name: "Disconnect Whisper",
    });
    await disconnectButton.click();

    const confirmDialog = page.getByRole("dialog");
    await expect(confirmDialog).toBeVisible({ timeout: 5000 });
    await expect(confirmDialog).toContainText("Disconnect OpenAI");

    // Should show replacement text and dropdown
    await expect(
      confirmDialog.getByText("Session history will be preserved")
    ).toBeVisible();

    // Disconnect button should be enabled because first replacement is auto-selected
    const confirmButton = confirmDialog.getByRole("button", {
      name: "Disconnect",
    });
    await expect(confirmButton).toBeEnabled();

    await expectElementScreenshot(confirmDialog, {
      name: "voice-disconnect-active-with-alt-modal",
    });
  });

  test("should show replacement when provider is default for both STT and TTS", async ({
    page,
  }) => {
    // OpenAI is default for both modes, ElevenLabs also configured
    const providers = [
      { ...FAKE_PROVIDERS.openai_active_both },
      { ...FAKE_PROVIDERS.elevenlabs_connected },
    ];
    await mockVoiceApis(page, providers);

    await page.goto(VOICE_URL);
    await page.waitForSelector("text=Speech to Text", { timeout: 20000 });

    const whisperCard = findModelCard(page, "voice-stt-whisper");
    await whisperCard.waitFor({ state: "visible", timeout: 10000 });

    await expectElementScreenshot(mainContainer(page), {
      name: "voice-disconnect-both-modes-before",
    });

    const disconnectButton = whisperCard.getByRole("button", {
      name: "Disconnect Whisper",
    });
    await disconnectButton.click();

    const confirmDialog = page.getByRole("dialog");
    await expect(confirmDialog).toBeVisible({ timeout: 5000 });
    await expect(confirmDialog).toContainText("Disconnect OpenAI");

    // Should mention both modes
    await expect(
      confirmDialog.getByText("speech-to-text or text-to-speech")
    ).toBeVisible();

    // Should show replacement dropdown
    await expect(
      confirmDialog.getByText("Session history will be preserved")
    ).toBeVisible();

    const confirmButton = confirmDialog.getByRole("button", {
      name: "Disconnect",
    });
    await expect(confirmButton).toBeEnabled();

    await expectElementScreenshot(confirmDialog, {
      name: "voice-disconnect-both-modes-modal",
    });
  });

  test("should show connect message when disconnecting active provider with no alternatives", async ({
    page,
  }) => {
    // Only OpenAI configured, active for STT — no other providers
    const providers = [{ ...FAKE_PROVIDERS.openai_active_stt }];
    await mockVoiceApis(page, providers);

    await page.goto(VOICE_URL);
    await page.waitForSelector("text=Speech to Text", { timeout: 20000 });

    const whisperCard = findModelCard(page, "voice-stt-whisper");
    await whisperCard.waitFor({ state: "visible", timeout: 10000 });

    await expectElementScreenshot(mainContainer(page), {
      name: "voice-disconnect-no-alt-before",
    });

    const disconnectButton = whisperCard.getByRole("button", {
      name: "Disconnect Whisper",
    });
    await disconnectButton.click();

    const confirmDialog = page.getByRole("dialog");
    await expect(confirmDialog).toBeVisible({ timeout: 5000 });
    await expect(confirmDialog).toContainText("Disconnect OpenAI");

    // Should show message about connecting another provider
    await expect(
      confirmDialog.getByText("Connect another provider")
    ).toBeVisible();

    // Disconnect button should be enabled
    const confirmButton = confirmDialog.getByRole("button", {
      name: "Disconnect",
    });
    await expect(confirmButton).toBeEnabled();

    await expectElementScreenshot(confirmDialog, {
      name: "voice-disconnect-no-alt-modal",
    });
  });

  test("should not show disconnect button for unconfigured provider", async ({
    page,
  }) => {
    await mockVoiceApis(page, []);

    await page.goto(VOICE_URL);
    await page.waitForSelector("text=Speech to Text", { timeout: 20000 });

    const whisperCard = findModelCard(page, "voice-stt-whisper");
    await whisperCard.waitFor({ state: "visible", timeout: 10000 });

    const disconnectButton = whisperCard.getByRole("button", {
      name: "Disconnect Whisper",
    });
    await expect(disconnectButton).not.toBeVisible();

    await expectElementScreenshot(mainContainer(page), {
      name: "voice-disconnect-unconfigured",
    });
  });
});
