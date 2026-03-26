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
      // OpenAI connected (not active for STT), ElevenLabs also connected
      const providers = [
        { ...FAKE_PROVIDERS.openai_connected },
        { ...FAKE_PROVIDERS.elevenlabs_connected },
      ];
      await mockVoiceApis(page, providers);

      await page.goto(VOICE_URL);
      await page.waitForSelector("text=Speech to Text", { timeout: 20000 });

      // Whisper card uses aria-label "voice-stt-whisper"
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

      // Verify confirmation modal
      const confirmDialog = page.getByRole("dialog");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });
      await expect(confirmDialog).toContainText("Disconnect Whisper");

      // Confirm disconnect
      const confirmButton = confirmDialog.getByRole("button", {
        name: "Disconnect",
      });
      await confirmButton.click();

      // Verify the card reverts to disconnected state
      await expect(
        whisperCard.getByRole("button", { name: "Connect" })
      ).toBeVisible({ timeout: 10000 });
    });

    test("should show disabled disconnect button for active STT provider", async ({
      page,
    }) => {
      // OpenAI is active for STT
      const providers = [{ ...FAKE_PROVIDERS.openai_active_stt }];
      await mockVoiceApis(page, providers);

      await page.goto(VOICE_URL);
      await page.waitForSelector("text=Speech to Text", { timeout: 20000 });

      const whisperCard = findModelCard(page, "voice-stt-whisper");
      await whisperCard.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = whisperCard.getByRole("button", {
        name: "Disconnect Whisper",
      });
      await expect(disconnectButton).toBeVisible();
      await expect(disconnectButton).toBeDisabled();
    });

    test("should not show disconnect button for unconfigured STT provider", async ({
      page,
    }) => {
      // No providers configured at all
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

      // TTS-1 card uses aria-label "voice-tts-tts-1"
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

      // Verify confirmation modal
      const confirmDialog = page.getByRole("dialog");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });
      await expect(confirmDialog).toContainText("Disconnect TTS-1");

      // Confirm disconnect
      const confirmButton = confirmDialog.getByRole("button", {
        name: "Disconnect",
      });
      await confirmButton.click();

      // Verify the card reverts to disconnected state
      await expect(
        tts1Card.getByRole("button", { name: "Connect" })
      ).toBeVisible({ timeout: 10000 });
    });

    test("should show disabled disconnect button for active TTS provider", async ({
      page,
    }) => {
      // OpenAI is active for TTS with tts-1
      const providers = [{ ...FAKE_PROVIDERS.openai_active_tts }];
      await mockVoiceApis(page, providers);

      await page.goto(VOICE_URL);
      await page.waitForSelector("text=Text to Speech", { timeout: 20000 });

      const tts1Card = findModelCard(page, "voice-tts-tts-1");
      await tts1Card.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = tts1Card.getByRole("button", {
        name: "Disconnect TTS-1",
      });
      await expect(disconnectButton).toBeVisible();
      await expect(disconnectButton).toBeDisabled();
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

    test("should allow TTS disconnect when same provider is active for STT only", async ({
      page,
    }) => {
      // OpenAI is active for STT (Whisper) but NOT for TTS —
      // TTS cards should still allow disconnect
      const providers = [
        {
          ...FAKE_PROVIDERS.openai_active_stt,
          is_default_tts: false,
          tts_model: null,
        },
      ];
      await mockVoiceApis(page, providers);

      await page.goto(VOICE_URL);
      await page.waitForSelector("text=Text to Speech", { timeout: 20000 });

      // TTS-1 is connected (provider has api key) but not active for TTS
      const tts1Card = findModelCard(page, "voice-tts-tts-1");
      await tts1Card.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = tts1Card.getByRole("button", {
        name: "Disconnect TTS-1",
      });
      await expect(disconnectButton).toBeVisible();
      await expect(disconnectButton).toBeEnabled();
    });

    test("should allow STT disconnect when same provider is active for TTS only", async ({
      page,
    }) => {
      // OpenAI is active for TTS but NOT for STT —
      // STT cards should still allow disconnect
      const providers = [
        {
          ...FAKE_PROVIDERS.openai_active_tts,
          is_default_stt: false,
          stt_model: null,
        },
      ];
      await mockVoiceApis(page, providers);

      await page.goto(VOICE_URL);
      await page.waitForSelector("text=Speech to Text", { timeout: 20000 });

      // Whisper is connected (provider has api key) but not active for STT
      const whisperCard = findModelCard(page, "voice-stt-whisper");
      await whisperCard.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = whisperCard.getByRole("button", {
        name: "Disconnect Whisper",
      });
      await expect(disconnectButton).toBeVisible();
      await expect(disconnectButton).toBeEnabled();
    });
  });
});
