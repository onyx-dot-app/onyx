import { SWR_KEYS } from "@/lib/swr-keys";
import type { TracingProviderType } from "@/lib/tracing/types";

const TRACING_PROVIDERS_URL = SWR_KEYS.tracingProviders;
const JSON_HEADERS = { "Content-Type": "application/json" };

async function parseErrorDetail(
  res: Response,
  fallback: string
): Promise<string> {
  try {
    const body = await res.json();
    return body?.detail ?? fallback;
  } catch {
    return fallback;
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
    throw new Error(
      await parseErrorDetail(testRes, "Failed to validate credentials.")
    );
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
    throw new Error(await parseErrorDetail(res, "Failed to connect provider."));
  }
}

export async function disconnectTracingProvider(
  providerType: TracingProviderType
): Promise<void> {
  const res = await fetch(`${TRACING_PROVIDERS_URL}/${providerType}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to disconnect provider.")
    );
  }
}
