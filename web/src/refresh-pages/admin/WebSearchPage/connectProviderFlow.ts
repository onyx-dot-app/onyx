export type ProviderTestPayload = {
  provider_type: string;
  api_key: string | null;
  use_stored_key: boolean;
  config: Record<string, string>;
};

export type ProviderUpsertPayload = {
  id: number | null;
  name: string;
  provider_type: string;
  api_key: string | null;
  api_key_changed: boolean;
  config: Record<string, string>;
  activate: boolean;
};

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

/**
 * Which web-search provider category we are configuring.
 * - `search`: search engine provider
 * - `content`: crawler/content provider used to fetch full pages
 */
export type WebProviderCategory = keyof typeof WEB_SEARCH_PROVIDER_ENDPOINTS;

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
    if (isNewProvider && !apiKey) {
      return;
    }
    if (apiKeyChangedForProvider && !apiKey) {
      return;
    }
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
          typeof (errorBody as any)?.detail === "string"
            ? (errorBody as any).detail
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
        typeof (errorBody as any)?.detail === "string"
          ? (errorBody as any).detail
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
