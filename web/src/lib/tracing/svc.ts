import { SWR_KEYS } from "@/lib/swr-keys";
import type { ApiTokenValue } from "@/lib/api-tokens/types";
import { parseErrorDetail } from "@/lib/fetcher";
import type { TracingProviderType } from "@/lib/tracing/types";

const TRACING_PROVIDERS_URL = SWR_KEYS.tracingProviders;
const JSON_HEADERS = { "Content-Type": "application/json" };

export interface ConnectTracingProviderArgs {
  providerType: TracingProviderType;
  /** The key to send, or `null` when the field is empty. */
  apiKey: ApiTokenValue | null;
  config: Record<string, string>;
}

export async function connectTracingProvider({
  providerType,
  apiKey,
  config,
}: ConnectTracingProviderArgs): Promise<void> {
  // Validate the credentials against the provider before persisting them.
  const testRes = await fetch(`${TRACING_PROVIDERS_URL}/test`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      provider_type: providerType,
      api_key: apiKey,
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
      api_key: apiKey,
      config,
      enabled: true,
    }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to connect provider."));
  }
}

// Disconnect by disabling the provider. Writing a disabled row overrides any
// env-var config (DB config wins), so this stops traces even when the provider
// was configured via environment variables.
export async function disconnectTracingProvider(
  providerType: TracingProviderType,
  config: Record<string, string>
): Promise<void> {
  const res = await fetch(TRACING_PROVIDERS_URL, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      provider_type: providerType,
      // Clear any stored credential rather than keeping it on a disabled row.
      api_key: null,
      config,
      enabled: false,
    }),
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to disconnect provider.")
    );
  }
}
