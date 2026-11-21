import { SWR_KEYS } from "@/lib/swr-keys";
import type { TracingProviderType } from "@/lib/tracing/types";

const TRACING_PROVIDERS_URL = SWR_KEYS.tracingProviders;
const JSON_HEADERS = { "Content-Type": "application/json" };

/**
 * The server's error detail, or "" without one. Callers show a translated
 * fallback for an empty message.
 */
async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    return typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
      ? body.detail
      : "";
  } catch {
    return "";
  }
}

export interface ConnectTracingProviderArgs {
  providerType: TracingProviderType;
  apiKey: string;
  apiKeyChanged: boolean;
  hasStoredKey: boolean;
  config: Record<string, string>;
}

export async function connectTracingProvider({
  providerType,
  apiKey,
  apiKeyChanged,
  hasStoredKey,
  config,
}: ConnectTracingProviderArgs): Promise<void> {
  // Validate the credentials against the provider before persisting them.
  const testRes = await fetch(`${TRACING_PROVIDERS_URL}/test`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      provider_type: providerType,
      api_key: apiKeyChanged ? apiKey : null,
      use_stored_key: !apiKeyChanged && hasStoredKey,
      config,
    }),
  });
  if (!testRes.ok) {
    throw new Error(await parseErrorDetail(testRes));
  }

  const res = await fetch(TRACING_PROVIDERS_URL, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      provider_type: providerType,
      api_key: apiKeyChanged ? apiKey : null,
      api_key_changed: apiKeyChanged,
      config,
      enabled: true,
    }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }
}

// Disconnect by disabling the provider. The key and settings stay, so it can
// be reconnected. Writing a disabled row overrides any env-var config (DB
// config wins), so this stops traces even when the provider was configured
// via environment variables.
export async function disconnectTracingProvider(
  providerType: TracingProviderType,
  config: Record<string, string>
): Promise<void> {
  await setTracingProviderEnabled(providerType, config, false);
}

/** Turns a disconnected provider back on with its saved key and settings. */
export async function reconnectTracingProvider(
  providerType: TracingProviderType,
  config: Record<string, string>
): Promise<void> {
  await setTracingProviderEnabled(providerType, config, true);
}

async function setTracingProviderEnabled(
  providerType: TracingProviderType,
  config: Record<string, string>,
  enabled: boolean
): Promise<void> {
  const res = await fetch(TRACING_PROVIDERS_URL, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      provider_type: providerType,
      api_key: null,
      // Keep the stored key.
      api_key_changed: false,
      config,
      enabled,
    }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }
}

/**
 * Deletes the provider's saved key and settings but keeps it switched off,
 * for a provider that env vars also configure. Deleting its row would let the
 * env config send traces again.
 */
export async function clearTracingProviderSettings(
  providerType: TracingProviderType
): Promise<void> {
  const res = await fetch(TRACING_PROVIDERS_URL, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      provider_type: providerType,
      api_key: null,
      api_key_changed: true,
      config: {},
      enabled: false,
    }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }
}

/** Deletes the provider's saved key and settings. */
export async function deleteTracingProvider(
  providerType: TracingProviderType
): Promise<void> {
  const res = await fetch(`${TRACING_PROVIDERS_URL}/${providerType}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }
}
