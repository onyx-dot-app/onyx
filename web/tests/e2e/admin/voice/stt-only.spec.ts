import { test, expect, Page } from "@playwright/test";
import { loginAs, loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";

const ADMIN_VOICE_URL = "/admin/configuration/voice";
const ADMIN_PROVIDERS_API = "**/api/admin/voice/providers";
const USER_VOICE_STATUS_API = "**/api/voice/status";

const OPENAI_STT_ONLY_PROVIDER = {
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
};

async function mockAdminProviders(
  page: Page,
  providers: (typeof OPENAI_STT_ONLY_PROVIDER)[]
) {
  await page.route(ADMIN_PROVIDERS_API, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, json: providers });
    } else {
      await route.continue();
    }
  });
}

async function mockVoiceStatus(
  page: Page,
  status: { stt_enabled: boolean; tts_enabled: boolean }
) {
  await page.route(USER_VOICE_STATUS_API, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, json: status });
    } else {
      await route.continue();
    }
  });
}

test.describe("Voice STT without TTS (ENG-3927)", () => {
  test("admin voice page renders STT as active with no TTS configured", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await mockAdminProviders(page, [OPENAI_STT_ONLY_PROVIDER]);

    await page.goto(ADMIN_VOICE_URL);
    await page.waitForSelector("text=Speech to Text", { timeout: 20000 });
    await expect(page.getByText("Text to Speech")).toBeVisible();

    // STT card for whisper exposes the Disconnect button only when the
    // provider is configured AND active for STT — proves the provider was
    // accepted with activate_tts=false.
    const whisperCard = page.getByLabel("voice-stt-whisper", { exact: true });
    await expect(whisperCard).toBeVisible({ timeout: 10000 });
    await expect(
      whisperCard.getByRole("button", { name: "Disconnect Whisper" })
    ).toBeVisible();

    // TTS cards belonging to the same provider remain in the
    // "connected but not selected" state — no Disconnect button surfaces
    // there because the provider isn't the default TTS.
    const tts1Card = page.getByLabel("voice-tts-tts-1", { exact: true });
    await expect(tts1Card).toBeVisible();
    await expect(
      tts1Card.getByRole("button", { name: "Disconnect tts-1" })
    ).not.toBeVisible();
  });

  test("chat shows mic but hides TTS controls when only STT is configured", async ({
    page,
  }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await mockVoiceStatus(page, { stt_enabled: true, tts_enabled: false });

    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    await expect(page.getByLabel("Start recording")).toBeVisible({
      timeout: 10000,
    });

    await sendMessage(page, "Say hello");

    // TTS playback button only renders on agent messages when
    // tts_enabled is true. With STT-only, the button must be absent.
    await expect(page.getByTestId("AgentMessage/tts-button")).toHaveCount(0);
  });
});
