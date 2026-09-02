import { expect, test, type Page, type Route } from "@playwright/test";
import { AdminVoicePage } from "@tests/e2e/pages/AdminVoicePage";
import { loginAs } from "@tests/e2e/utils/auth";

interface VoiceProviderPayload {
  id?: number;
  name: string;
  provider_type: string;
  is_default_stt: boolean;
  is_default_tts: boolean;
  stt_model: string | null;
  tts_model: string | null;
  default_voice: string | null;
  api_key: string | null;
  api_secret: string | null;
  target_uri: string | null;
  custom_config: Record<string, unknown> | null;
}

type RequestBody = Record<string, unknown>;

const ZOOM_PROVIDER: VoiceProviderPayload = {
  id: 7,
  name: "Zoom Scribe",
  provider_type: "zoom",
  is_default_stt: true,
  is_default_tts: false,
  stt_model: "scribe-live",
  tts_model: null,
  default_voice: null,
  api_key: "zm-***masked-key***",
  api_secret: "zs-***masked-secret***",
  target_uri: null,
  custom_config: {
    language: "xx-XX",
    passthrough: "keep-me",
  },
};

async function routeVoiceProviders(
  page: Page,
  providers: VoiceProviderPayload[],
  capturedUpserts: RequestBody[]
): Promise<void> {
  await page.route("**/api/admin/voice/providers", async (route: Route) => {
    const request = route.request();

    if (request.method() === "GET") {
      await route.fulfill({ status: 200, json: providers });
      return;
    }

    if (request.method() === "POST") {
      capturedUpserts.push(request.postDataJSON() as RequestBody);
      await route.fulfill({ status: 200, json: {} });
      return;
    }

    await route.continue();
  });
}

async function routeVoiceTests(
  page: Page,
  capturedTests: RequestBody[]
): Promise<void> {
  await page.route("**/api/admin/voice/providers/test", async (route) => {
    capturedTests.push(route.request().postDataJSON() as RequestBody);
    await route.fulfill({ status: 200, json: {} });
  });
}

test.describe("Zoom Scribe voice provider", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test("creates Zoom Scribe as an STT-only provider with secret and language", async ({
    page,
  }) => {
    const capturedTests: RequestBody[] = [];
    const capturedUpserts: RequestBody[] = [];
    await routeVoiceProviders(page, [], capturedUpserts);
    await routeVoiceTests(page, capturedTests);

    const voicePage = new AdminVoicePage(page);
    await voicePage.goto();
    await voicePage.expectZoomCardUnderSpeechToTextOnly();
    await voicePage.openZoomSetupModal();
    await voicePage.expectZoomSetupFields();
    await voicePage.expectLanguageValue("en-US");

    await voicePage.fillZoomCredentials({
      apiKey: "zoom-raw-key",
      apiSecret: "zoom-raw-secret",
    });
    await voicePage.selectLanguage("fr-FR");
    await voicePage.connectZoom();

    await expect.poll(() => capturedTests.length).toBe(1);
    await expect.poll(() => capturedUpserts.length).toBe(1);

    expect(capturedTests[0]).toMatchObject({
      provider_type: "zoom",
      api_key: "zoom-raw-key",
      api_secret: "zoom-raw-secret",
      use_stored_key: false,
      use_stored_secret: false,
      custom_config: { language: "fr-FR" },
    });
    expect(capturedUpserts[0]).toMatchObject({
      name: "Zoom Scribe",
      provider_type: "zoom",
      api_key: "zoom-raw-key",
      api_secret: "zoom-raw-secret",
      api_key_changed: true,
      api_secret_changed: true,
      stt_model: "scribe-live",
      tts_model: null,
      activate_stt: true,
      activate_tts: false,
      custom_config: { language: "fr-FR" },
    });
  });

  test("edits Zoom Scribe without resending masked credentials", async ({
    page,
  }) => {
    const capturedTests: RequestBody[] = [];
    const capturedUpserts: RequestBody[] = [];
    await routeVoiceProviders(page, [ZOOM_PROVIDER], capturedUpserts);
    await routeVoiceTests(page, capturedTests);

    const voicePage = new AdminVoicePage(page);
    await voicePage.goto();
    await voicePage.expectZoomCardUnderSpeechToTextOnly();
    await voicePage.openZoomEditModal();
    await voicePage.expectZoomSetupFields();
    await voicePage.expectLanguageValue("en-US");

    await voicePage.selectLanguage("pt-BR");
    await voicePage.updateZoom();

    await expect.poll(() => capturedTests.length).toBe(1);
    await expect.poll(() => capturedUpserts.length).toBe(1);

    expect(capturedTests[0]).toMatchObject({
      provider_type: "zoom",
      use_stored_key: true,
      use_stored_secret: true,
      custom_config: { language: "pt-BR", passthrough: "keep-me" },
    });
    expect(capturedTests[0]).not.toHaveProperty("api_key");
    expect(capturedTests[0]).not.toHaveProperty("api_secret");

    expect(capturedUpserts[0]).toMatchObject({
      id: 7,
      name: "Zoom Scribe",
      provider_type: "zoom",
      api_key_changed: false,
      api_secret_changed: false,
      stt_model: "scribe-live",
      tts_model: null,
      activate_stt: true,
      activate_tts: false,
      custom_config: { language: "pt-BR", passthrough: "keep-me" },
    });
    expect(capturedUpserts[0]).not.toHaveProperty("api_key");
    expect(capturedUpserts[0]).not.toHaveProperty("api_secret");
  });
});
