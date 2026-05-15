import { test, expect, Page } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";

const USER_VOICE_STATUS_API = "**/api/voice/status";

interface VoiceStatusPayload {
  stt_enabled: boolean;
  tts_enabled: boolean;
}

async function mockVoiceStatus(
  page: Page,
  status: VoiceStatusPayload
): Promise<void> {
  await page.route(USER_VOICE_STATUS_API, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, json: status });
    } else {
      await route.continue();
    }
  });
}

test.describe("Voice STT without TTS (ENG-3927)", () => {
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
