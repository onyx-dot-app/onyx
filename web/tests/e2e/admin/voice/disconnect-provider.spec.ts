import { test, expect, Page, Locator } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

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
  openai_active_tts: {
    id: 1,
    name: "openai",
    provider_type: "openai",
    is_default_stt: false,
    is_default_tts: true,
    stt_model: null,
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

  test.describe("Speech to Text", () => {
    test("should disconnect a connected (non-active) STT provider", async ({
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

      const disconnectButton = whisperCard.getByRole("button", {
        name: "Disconnect Whisper",
      });
      await expect(disconnectButton).toBeVisible();
      await expect(disconnectButton).toBeEnabled();

      // Mock the DELETE to succeed
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

      // Verify confirmation modal — non-active provider shows simple message
      const confirmDialog = page.getByRole("dialog");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });
      await expect(confirmDialog).toContainText("Disconnect Whisper");

      const confirmButton = confirmDialog.getByRole("button", {
        name: "Disconnect",
      });
      await confirmButton.click();

      // Verify the card reverts to disconnected state
      await expect(
        whisperCard.getByRole("button", { name: "Connect" })
      ).toBeVisible({ timeout: 10000 });
    });

    test("should show replacement dropdown when disconnecting active STT provider with alternatives", async ({
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

      const disconnectButton = whisperCard.getByRole("button", {
        name: "Disconnect Whisper",
      });
      await expect(disconnectButton).toBeVisible();
      await expect(disconnectButton).toBeEnabled();

      await disconnectButton.click();

      const confirmDialog = page.getByRole("dialog");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });
      await expect(confirmDialog).toContainText("Disconnect Whisper");

      // Should show replacement text and dropdown
      await expect(
        confirmDialog.getByText("Choose a replacement")
      ).toBeVisible();

      // Disconnect button should be enabled because first replacement is auto-selected
      const confirmButton = confirmDialog.getByRole("button", {
        name: "Disconnect",
      });
      await expect(confirmButton).toBeEnabled();
    });

    test("should show warning when disconnecting active STT provider with no alternatives", async ({
      page,
    }) => {
      // Only OpenAI configured, active for STT — no other providers
      const providers = [{ ...FAKE_PROVIDERS.openai_active_stt }];
      await mockVoiceApis(page, providers);

      await page.goto(VOICE_URL);
      await page.waitForSelector("text=Speech to Text", { timeout: 20000 });

      const whisperCard = findModelCard(page, "voice-stt-whisper");
      await whisperCard.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = whisperCard.getByRole("button", {
        name: "Disconnect Whisper",
      });
      await disconnectButton.click();

      const confirmDialog = page.getByRole("dialog");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });

      // Should warn that STT will be disabled
      await expect(
        confirmDialog.getByText("until you configure another provider")
      ).toBeVisible();

      // Disconnect button should still be enabled (user accepts the consequence)
      const confirmButton = confirmDialog.getByRole("button", {
        name: "Disconnect",
      });
      await expect(confirmButton).toBeEnabled();
    });

    test("should not show disconnect button for unconfigured STT provider", async ({
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
    });
  });

  test.describe("Text to Speech", () => {
    test("should disconnect a connected (non-active) TTS provider", async ({
      page,
    }) => {
      const providers = [
        { ...FAKE_PROVIDERS.openai_connected },
        { ...FAKE_PROVIDERS.elevenlabs_connected },
      ];
      await mockVoiceApis(page, providers);

      await page.goto(VOICE_URL);
      await page.waitForSelector("text=Text to Speech", { timeout: 20000 });

      const tts1Card = findModelCard(page, "voice-tts-tts-1");
      await tts1Card.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = tts1Card.getByRole("button", {
        name: "Disconnect TTS-1",
      });
      await expect(disconnectButton).toBeVisible();
      await expect(disconnectButton).toBeEnabled();

      // Mock the DELETE to succeed
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

      const confirmDialog = page.getByRole("dialog");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });
      await expect(confirmDialog).toContainText("Disconnect TTS-1");

      const confirmButton = confirmDialog.getByRole("button", {
        name: "Disconnect",
      });
      await confirmButton.click();

      await expect(
        tts1Card.getByRole("button", { name: "Connect" })
      ).toBeVisible({ timeout: 10000 });
    });

    test("should show replacement dropdown when disconnecting active TTS provider with alternatives", async ({
      page,
    }) => {
      // OpenAI is active for TTS, ElevenLabs is also configured
      const providers = [
        { ...FAKE_PROVIDERS.openai_active_tts },
        { ...FAKE_PROVIDERS.elevenlabs_connected },
      ];
      await mockVoiceApis(page, providers);

      await page.goto(VOICE_URL);
      await page.waitForSelector("text=Text to Speech", { timeout: 20000 });

      const tts1Card = findModelCard(page, "voice-tts-tts-1");
      await tts1Card.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = tts1Card.getByRole("button", {
        name: "Disconnect TTS-1",
      });
      await disconnectButton.click();

      const confirmDialog = page.getByRole("dialog");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });

      // Should show replacement dropdown
      await expect(
        confirmDialog.getByText("Choose a replacement")
      ).toBeVisible();

      // Disconnect should be enabled because first replacement is auto-selected
      const confirmButton = confirmDialog.getByRole("button", {
        name: "Disconnect",
      });
      await expect(confirmButton).toBeEnabled();
    });

    test("should not show disconnect button for unconfigured TTS provider", async ({
      page,
    }) => {
      await mockVoiceApis(page, []);

      await page.goto(VOICE_URL);
      await page.waitForSelector("text=Text to Speech", { timeout: 20000 });

      const tts1Card = findModelCard(page, "voice-tts-tts-1");
      await tts1Card.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = tts1Card.getByRole("button", {
        name: "Disconnect TTS-1",
      });
      await expect(disconnectButton).not.toBeVisible();
    });
  });
});
