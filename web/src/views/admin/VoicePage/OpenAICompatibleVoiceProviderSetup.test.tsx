import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { VoiceProviderSetupModal } from "@/views/admin/VoicePage/shared";
import { VoiceProviderType, type VoiceProviderView } from "@/lib/voice/types";

const API_BASE = "http://host.docker.internal:8000/v1";
const UPDATED_API_BASE = "http://host.docker.internal:8001/v1";
const MODEL = "whisper-large-v3";

function response(body: object = {}): Response {
  return {
    ok: true,
    json: async () => body,
  } as Response;
}

function renderSetup(existingProvider: VoiceProviderView | null = null) {
  const onSuccess = jest.fn();
  render(
    <VoiceProviderSetupModal
      providerType={VoiceProviderType.OPENAI_COMPATIBLE}
      existingProvider={existingProvider}
      mode="stt"
      onSuccess={onSuccess}
    />
  );
  return onSuccess;
}

function existingProvider(apiKey: string): VoiceProviderView {
  return {
    id: 41,
    name: "OpenAI-Compatible",
    provider_type: VoiceProviderType.OPENAI_COMPATIBLE,
    is_default_stt: true,
    is_default_tts: false,
    stt_model: MODEL,
    tts_model: null,
    default_voice: null,
    api_key: apiKey,
    target_uri: API_BASE,
    custom_config: null,
  };
}

describe("OpenAI-compatible voice provider setup", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue(response());
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  test("requires an API base and model but not an API key", async () => {
    const user = setupUser();
    const onSuccess = renderSetup();
    const connect = screen.getByRole("button", { name: /^Connect$/ });

    await user.type(screen.getByLabelText("API Base URL"), API_BASE);
    expect(connect).toBeDisabled();

    await user.type(screen.getByLabelText("STT Model"), MODEL);
    await waitFor(() => expect(connect).toBeEnabled());
    await user.click(connect);

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    const testRequest = JSON.parse(fetchSpy.mock.calls[0][1].body as string);
    const upsertRequest = JSON.parse(fetchSpy.mock.calls[1][1].body as string);
    expect(testRequest).toMatchObject({
      provider_type: VoiceProviderType.OPENAI_COMPATIBLE,
      api_base: API_BASE,
      stt_model: MODEL,
    });
    expect(testRequest.api_key).toBeUndefined();
    expect(upsertRequest).toMatchObject({
      provider_type: VoiceProviderType.OPENAI_COMPATIBLE,
      api_base: API_BASE,
      stt_model: MODEL,
      api_key_changed: false,
    });
  });

  test("keeps the masked API key when editing", async () => {
    const user = setupUser();
    renderSetup(existingProvider("sk-...masked"));

    const apiBaseInput = screen.getByLabelText("API Base URL");
    await user.clear(apiBaseInput);
    await user.type(apiBaseInput, UPDATED_API_BASE);
    const modelInput = screen.getByLabelText("STT Model");
    await user.clear(modelInput);
    await user.type(modelInput, `${MODEL}-turbo`);
    await user.click(screen.getByRole("button", { name: "Update" }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    const testRequest = JSON.parse(fetchSpy.mock.calls[0][1].body as string);
    const upsertRequest = JSON.parse(fetchSpy.mock.calls[1][1].body as string);
    expect(testRequest).toMatchObject({
      api_base: UPDATED_API_BASE,
      stt_model: `${MODEL}-turbo`,
      use_stored_key: true,
    });
    expect(testRequest.api_key).toBeUndefined();
    expect(testRequest.target_uri).toBeUndefined();
    expect(upsertRequest).toMatchObject({
      id: 41,
      api_key_changed: false,
      api_base: UPDATED_API_BASE,
      stt_model: `${MODEL}-turbo`,
    });
    expect(upsertRequest.api_key).toBeUndefined();
    expect(upsertRequest.target_uri).toBeUndefined();
  });

  test("sends null when clearing the stored API key", async () => {
    const user = setupUser();
    renderSetup(existingProvider("sk-...masked"));

    await user.clear(screen.getByLabelText("API Key"));
    await user.click(screen.getByRole("button", { name: "Update" }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    const testRequest = JSON.parse(fetchSpy.mock.calls[0][1].body as string);
    const upsertRequest = JSON.parse(fetchSpy.mock.calls[1][1].body as string);
    expect(testRequest).toMatchObject({
      api_key: null,
      use_stored_key: false,
    });
    expect(upsertRequest).toMatchObject({
      api_key: null,
      api_key_changed: true,
    });
  });
});
