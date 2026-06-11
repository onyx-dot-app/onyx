const VOICE_PROVIDERS_URL = "/api/admin/voice/providers";

/** Sets a provider as the active STT or TTS default. Optionally pins a specific TTS model. */
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

/** Removes the STT or TTS default status from a provider without deleting it. */
export async function deactivateVoiceProvider(
  providerId: number,
  mode: "stt" | "tts"
): Promise<Response> {
  return fetch(`${VOICE_PROVIDERS_URL}/${providerId}/deactivate-${mode}`, {
    method: "POST",
  });
}

/** Validates provider credentials with a live API call before saving. */
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

/** Creates or updates a voice provider configuration. */
export async function upsertVoiceProvider(
  request: Record<string, unknown>
): Promise<Response> {
  return fetch(VOICE_PROVIDERS_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** Fetches the list of available voices for a given provider type. */
export async function fetchVoicesByType(
  providerType: string
): Promise<Response> {
  return fetch(`/api/admin/voice/voices?provider_type=${providerType}`);
}

/** Permanently removes a voice provider and its stored credentials. */
export async function deleteVoiceProvider(
  providerId: number
): Promise<Response> {
  return fetch(`${VOICE_PROVIDERS_URL}/${providerId}`, { method: "DELETE" });
}

/** Fetches all configured LLM providers (used to copy API keys into voice providers). */
export async function fetchLLMProviders(): Promise<Response> {
  return fetch("/api/admin/llm/provider");
}
