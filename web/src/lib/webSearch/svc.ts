import { CONTENT_PROVIDER_DETAILS } from "@/lib/webSearch/utils";
import type {
  WebProviderCategory,
  WebContentProviderView,
  ProviderTestPayload,
  ProviderUpsertPayload,
} from "@/lib/webSearch/types";

// ── Internal helpers ──────────────────────────────────────────────────────────

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

const WEB_SEARCH_PROVIDER_ENDPOINTS = {
  search: {
    upsertUrl: "/api/admin/web-search/search-providers",
    testUrl: "/api/admin/web-search/search-providers/test",
  },
  content: {
    upsertUrl: "/api/admin/web-search/content-providers",
    testUrl: "/api/admin/web-search/content-providers/test",
  },
} as const;

// ── Search provider actions ───────────────────────────────────────────────────

export async function activateSearchProvider(
  providerId: number
): Promise<void> {
  const res = await fetch(
    `/api/admin/web-search/search-providers/${providerId}/activate`,
    { method: "POST", headers: { "Content-Type": "application/json" } }
  );
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to set provider as default.")
    );
  }
}

export async function deactivateSearchProvider(
  providerId: number
): Promise<void> {
  const res = await fetch(
    `/api/admin/web-search/search-providers/${providerId}/deactivate`,
    { method: "POST", headers: { "Content-Type": "application/json" } }
  );
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to deactivate provider.")
    );
  }
}

// ── Content provider actions ──────────────────────────────────────────────────

export async function activateContentProvider(
  provider: WebContentProviderView
): Promise<void> {
  if (provider.provider_type === "onyx_web_crawler") {
    const res = await fetch(
      "/api/admin/web-search/content-providers/reset-default",
      { method: "POST", headers: { "Content-Type": "application/json" } }
    );
    if (!res.ok) {
      throw new Error(
        await parseErrorDetail(res, "Failed to set crawler as default.")
      );
    }
  } else if (provider.id > 0) {
    const res = await fetch(
      `/api/admin/web-search/content-providers/${provider.id}/activate`,
      { method: "POST", headers: { "Content-Type": "application/json" } }
    );
    if (!res.ok) {
      throw new Error(
        await parseErrorDetail(res, "Failed to set crawler as default.")
      );
    }
  } else {
    const payload = {
      id: null,
      name:
        provider.name ||
        CONTENT_PROVIDER_DETAILS[provider.provider_type]?.label ||
        provider.provider_type,
      provider_type: provider.provider_type,
      api_key: null,
      api_key_changed: false,
      config: provider.config ?? null,
      activate: true,
    };
    const res = await fetch("/api/admin/web-search/content-providers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(
        await parseErrorDetail(res, "Failed to set crawler as default.")
      );
    }
  }
}

export async function deactivateContentProvider(
  providerId: number,
  providerType: string
): Promise<void> {
  const endpoint =
    providerType === "onyx_web_crawler" || providerId < 0
      ? "/api/admin/web-search/content-providers/reset-default"
      : `/api/admin/web-search/content-providers/${providerId}/deactivate`;

  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to deactivate provider.")
    );
  }
}

export async function disconnectProvider(
  id: number,
  category: "search" | "content",
  replacementProviderId: string | null
): Promise<void> {
  if (replacementProviderId && replacementProviderId !== "__none__") {
    const repId = Number(replacementProviderId);
    const activateEndpoint =
      category === "search"
        ? `/api/admin/web-search/search-providers/${repId}/activate`
        : `/api/admin/web-search/content-providers/${repId}/activate`;
    const activateRes = await fetch(activateEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!activateRes.ok) {
      throw new Error(
        await parseErrorDetail(
          activateRes,
          "Failed to activate replacement provider."
        )
      );
    }
  }

  const res = await fetch(`/api/admin/web-search/${category}-providers/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to disconnect provider.")
    );
  }
}

// ── Connect / update provider flow ────────────────────────────────────────────

export type ConnectProviderFlowArgs = {
  category: WebProviderCategory;
  providerType: string;

  existingProviderId: number | null;
  existingProviderName: string | null;
  existingProviderHasApiKey: boolean;

  displayName: string;

  providerRequiresApiKey: boolean;
  apiKeyChangedForProvider: boolean;
  apiKey: string;

  config: Record<string, string>;
  configChanged: boolean;

  onValidating: (message: string) => void;
  onSaving: (message: string) => void;
  onError: (message: string) => void;
  onClose: () => void;

  mutate: () => Promise<unknown>;
};

export async function connectProviderFlow({
  category,
  providerType,
  existingProviderId,
  existingProviderName,
  existingProviderHasApiKey,
  displayName,
  providerRequiresApiKey,
  apiKeyChangedForProvider,
  apiKey,
  config,
  configChanged,
  onValidating,
  onSaving,
  onError,
  onClose,
  mutate,
}: ConnectProviderFlowArgs): Promise<void> {
  const { testUrl, upsertUrl } = WEB_SEARCH_PROVIDER_ENDPOINTS[category];
  const isNewProvider = existingProviderId == null;
  const needsValidation =
    isNewProvider || apiKeyChangedForProvider || configChanged;

  const msg = {
    validating: "Validating configuration...",
    activating: "Activating provider...",
    validatedThenActivating: "Configuration validated. Activating provider...",
    validationFailedFallback: "Failed to validate configuration.",
    activateFailedFallback: "Failed to activate provider.",
  };

  if (providerRequiresApiKey) {
    if (isNewProvider && !apiKey) return;
    if (apiKeyChangedForProvider && !apiKey) return;
  }

  try {
    if (needsValidation) {
      onValidating(msg.validating);

      const testPayload: ProviderTestPayload = {
        provider_type: providerType,
        api_key: apiKeyChangedForProvider ? apiKey : null,
        use_stored_key:
          providerRequiresApiKey &&
          !apiKeyChangedForProvider &&
          existingProviderHasApiKey,
        config,
      };

      const testResponse = await fetch(testUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(testPayload),
      });

      if (!testResponse.ok) {
        const errorBody = await testResponse.json().catch(() => ({}));
        throw new Error(
          typeof (errorBody as { detail?: unknown })?.detail === "string"
            ? (errorBody as { detail: string }).detail
            : msg.validationFailedFallback
        );
      }

      onSaving(msg.validatedThenActivating);
    } else {
      onSaving(msg.activating);
    }

    const upsertPayload: ProviderUpsertPayload = {
      id: existingProviderId,
      name: existingProviderName ?? displayName,
      provider_type: providerType,
      api_key: apiKeyChangedForProvider ? apiKey : null,
      api_key_changed: apiKeyChangedForProvider,
      config,
      activate: true,
    };

    const upsertResponse = await fetch(upsertUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(upsertPayload),
    });

    if (!upsertResponse.ok) {
      const errorBody = await upsertResponse.json().catch(() => ({}));
      throw new Error(
        typeof (errorBody as { detail?: unknown })?.detail === "string"
          ? (errorBody as { detail: string }).detail
          : msg.activateFailedFallback
      );
    }

    await mutate();
    onClose();
  } catch (e) {
    const message =
      e instanceof Error ? e.message : "Unexpected error occurred.";
    onError(message);
  }
}
