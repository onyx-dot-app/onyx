import { expect, test, type Page, type Route } from "@playwright/test";
import {
  VoiceProviderType,
  type VoiceProviderTestRequest,
  type VoiceProviderUpsertRequest,
  type VoiceProviderView,
} from "@/lib/voice/types";
import { AdminVoicePage } from "@tests/e2e/pages/AdminVoicePage";
import { loginAs } from "@tests/e2e/utils/auth";

const API_BASE = "http://host.docker.internal:8000/v1";
const UPDATED_API_BASE = "http://host.docker.internal:8001/v1";
const INITIAL_MODEL = "whisper-large-v3";
const UPDATED_MODEL = "whisper-large-v3-turbo";

interface VoiceApiMock {
  testRequests: VoiceProviderTestRequest[];
  upsertRequests: VoiceProviderUpsertRequest[];
}

async function mockVoiceApis(page: Page): Promise<VoiceApiMock> {
  let provider: VoiceProviderView | null = null;
  const testRequests: VoiceProviderTestRequest[] = [];
  const upsertRequests: VoiceProviderUpsertRequest[] = [];

  await page.route("**/api/admin/voice/providers**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (request.method() === "GET" && path.endsWith("/providers")) {
      await route.fulfill({ status: 200, json: provider ? [provider] : [] });
      return;
    }

    if (request.method() === "POST" && path.endsWith("/providers/test")) {
      testRequests.push(request.postDataJSON() as VoiceProviderTestRequest);
      await route.fulfill({ status: 200, json: { status: "ok" } });
      return;
    }

    if (request.method() === "POST" && path.endsWith("/providers")) {
      const body = request.postDataJSON() as VoiceProviderUpsertRequest;
      upsertRequests.push(body);
      provider = {
        id: 41,
        name: body.name,
        provider_type: body.provider_type,
        is_default_stt: true,
        is_default_tts: false,
        stt_model: body.stt_model ?? null,
        tts_model: null,
        default_voice: null,
        api_key: body.api_key ? "sk-...mocked" : null,
        target_uri: body.api_base ?? null,
        custom_config: body.custom_config ?? null,
      };
      await route.fulfill({ status: 200, json: provider });
      return;
    }

    if (request.method() === "DELETE" && path.endsWith("/providers/41")) {
      provider = null;
      await route.fulfill({ status: 200, json: { status: "ok" } });
      return;
    }

    await route.fulfill({ status: 200, json: { status: "ok" } });
  });

  return { testRequests, upsertRequests };
}

test("admin configures, edits, and disconnects OpenAI-compatible STT", async ({
  page,
}) => {
  await page.context().clearCookies();
  await loginAs(page, "admin");
  const requests = await mockVoiceApis(page);
  const voicePage = new AdminVoicePage(page);

  await voicePage.goto();
  await voicePage.openSetup();
  await voicePage.expectSetupGuidance();
  await voicePage.fillSetup(API_BASE, INITIAL_MODEL);
  await voicePage.saveSetup();
  await voicePage.expectSelected();

  expect(requests.testRequests[0]).toMatchObject({
    provider_type: VoiceProviderType.OPENAI_COMPATIBLE,
    api_base: API_BASE,
    stt_model: INITIAL_MODEL,
  });
  expect(requests.testRequests[0]?.api_key).toBeUndefined();
  expect(requests.upsertRequests[0]).toMatchObject({
    provider_type: VoiceProviderType.OPENAI_COMPATIBLE,
    api_base: API_BASE,
    stt_model: INITIAL_MODEL,
    activate_stt: true,
  });

  await voicePage.openEdit();
  await voicePage.expectSetupValues(API_BASE, INITIAL_MODEL);
  await voicePage.updateSetup(UPDATED_API_BASE, UPDATED_MODEL);

  expect(requests.testRequests[1]).toMatchObject({
    api_base: UPDATED_API_BASE,
    stt_model: UPDATED_MODEL,
    use_stored_key: false,
  });
  expect(requests.testRequests[1]?.target_uri).toBeUndefined();
  expect(requests.upsertRequests[1]).toMatchObject({
    id: 41,
    api_base: UPDATED_API_BASE,
    stt_model: UPDATED_MODEL,
  });
  expect(requests.upsertRequests[1]?.target_uri).toBeUndefined();

  await voicePage.disconnect();
});
