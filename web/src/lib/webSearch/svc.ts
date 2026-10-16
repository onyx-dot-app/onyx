import { CONTENT_PROVIDER_DETAILS } from "@/lib/webSearch/utils";
import type { ApiTokenValue } from "@/lib/api-tokens/types";
import { parseErrorDetail } from "@/lib/fetcher";
import {
  initialApiTokenValue,
  toApiTokenPayload,
} from "@/lib/api-tokens/utils";
import type {
  WebProviderCategory,
  WebContentProviderView,
  ProviderTestPayload,
  ProviderUpsertPayload,
} from "@/lib/webSearch/types";

// ── Internal helpers ──────────────────────────────────────────────────────────

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
      // A placeholder card can carry the key its sibling side already uses.
      api_key: toApiTokenPayload(initialApiTokenValue(provider.api_token_id)),
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
  category: "search" | "content"
): Promise<void> {
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

  displayName: string;

  providerRequiresApiKey: boolean;
  /** The key to send, or `null` when the field is empty. */
  apiKey: ApiTokenValue | undefined;
  apiKeyChanged: boolean;

  config: Record<string, string>;
  configChanged: boolean;

  onValidating: (message: string) => void;
  onSaving: (message: string) => void;
  onError: (message: string) => void;
  onClose: () => void;

  mutate: () => Promise<void>;
};

export async function connectProviderFlow({
  category,
  providerType,
  existingProviderId,
  existingProviderName,
  displayName,
  providerRequiresApiKey,
  apiKey,
  apiKeyChanged,
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
  const needsValidation = isNewProvider || apiKeyChanged || configChanged;

  const msg = {
    validating: "Validating configuration...",
    activating: "Activating provider...",
    validatedThenActivating: "Configuration validated. Activating provider...",
    validationFailedFallback: "Failed to validate configuration.",
    activateFailedFallback: "Failed to activate provider.",
  };

  if (providerRequiresApiKey && apiKey === undefined) return;

  try {
    if (needsValidation) {
      onValidating(msg.validating);

      const testPayload: ProviderTestPayload = {
        provider_type: providerType,
        api_key: apiKey,
        config,
      };

      const testResponse = await fetch(testUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(testPayload),
      });

      if (!testResponse.ok) {
        throw new Error(
          await parseErrorDetail(testResponse, msg.validationFailedFallback)
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
      api_key: apiKey,
      config,
      activate: true,
    };

    const upsertResponse = await fetch(upsertUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(upsertPayload),
    });

    if (!upsertResponse.ok) {
      throw new Error(
        await parseErrorDetail(upsertResponse, msg.activateFailedFallback)
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
