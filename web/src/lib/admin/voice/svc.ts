const VOICE_PROVIDERS_URL = "/api/admin/voice/providers";

export async function activateVoiceProvider(
  providerId: number,
  mode: "stt" | "tts",
  ttsModel?: string
): Promise<Response> {
  const url = new URL(
    `${VOICE_PROVIDERS_URL}/${providerId}/activate-${mode}`,
    window.location.origin
  );
  if (mode === "tts" && ttsModel) {
    url.searchParams.set("tts_model", ttsModel);
  }
  return fetch(url.toString(), { method: "POST" });
}

export async function deactivateVoiceProvider(
  providerId: number,
  mode: "stt" | "tts"
): Promise<Response> {
  return fetch(`${VOICE_PROVIDERS_URL}/${providerId}/deactivate-${mode}`, {
    method: "POST",
  });
}

export async function testVoiceProvider(request: {
  provider_type: string;
  api_key?: string;
  target_uri?: string;
  use_stored_key?: boolean;
}): Promise<Response> {
  return fetch(`${VOICE_PROVIDERS_URL}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export async function upsertVoiceProvider(
  request: Record<string, unknown>
): Promise<Response> {
  return fetch(VOICE_PROVIDERS_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export async function fetchVoicesByType(
  providerType: string
): Promise<Response> {
  return fetch(`/api/admin/voice/voices?provider_type=${providerType}`);
}

export async function fetchLLMProviders(): Promise<Response> {
  return fetch("/api/admin/llm/provider");
}
