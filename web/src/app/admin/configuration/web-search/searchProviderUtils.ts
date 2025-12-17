export type WebSearchProviderType = "google_pse" | "serper" | "exa" | "searxng";

export const SEARCH_PROVIDERS_URL = "/api/admin/web-search/search-providers";

export const SEARCH_PROVIDER_DETAILS: Record<
  WebSearchProviderType,
  {
    label: string;
    subtitle: string;
    helper: string;
    logoSrc?: string;
    apiKeyUrl?: string;
  }
> = {
  exa: {
    label: "Exa",
    subtitle: "Exa.ai",
    helper: "Connect to Exa to set up web search.",
    logoSrc: "/Exa.svg",
    apiKeyUrl: "https://dashboard.exa.ai/api-keys",
  },
  serper: {
    label: "Serper",
    subtitle: "Serper.dev",
    helper: "Connect to Serper to set up web search.",
    logoSrc: "/Serper.svg",
    apiKeyUrl: "https://serper.dev/api-key",
  },
  google_pse: {
    label: "Google PSE",
    subtitle: "Google",
    helper: "Connect to Google PSE to set up web search.",
    logoSrc: "/Google.svg",
    apiKeyUrl: "https://programmablesearchengine.google.com/controlpanel/all",
  },
  searxng: {
    label: "SearXNG",
    subtitle: "SearXNG",
    helper: "Connect to SearXNG to set up web search.",
    logoSrc: "/SearXNG.svg",
  },
};

/**
 * Display order for built-in providers.
 * Derived from insertion order of `SEARCH_PROVIDER_DETAILS` for a single source of truth.
 */
export const SEARCH_PROVIDER_ORDER = Object.keys(
  SEARCH_PROVIDER_DETAILS
) as WebSearchProviderType[];

export function getSearchProviderDisplayLabel(
  providerType: string,
  providerName?: string | null
): string {
  if (providerName) return providerName;
  return (
    (SEARCH_PROVIDER_DETAILS as Record<string, { label: string }>)[providerType]
      ?.label ?? providerType
  );
}

export type SearchProviderConfig = Record<string, string> | null | undefined;

export type SearchProviderLike =
  | {
      has_api_key: boolean;
      config: SearchProviderConfig;
    }
  | null
  | undefined;

type SearchProviderCaps = {
  requiresApiKey: boolean;
  /** Keys required in `config` to consider the provider configured / connectable. */
  requiredConfigKeys: string[];
  /**
   * Some providers historically stored config under different keys.
   * When reading stored config, we consider these aliases equivalent.
   */
  storedConfigAliases?: Record<string, string[]>;
};

export const SEARCH_PROVIDER_CAPS: Record<
  WebSearchProviderType,
  SearchProviderCaps
> = {
  exa: {
    requiresApiKey: true,
    requiredConfigKeys: [],
  },
  serper: {
    requiresApiKey: true,
    requiredConfigKeys: [],
  },
  google_pse: {
    requiresApiKey: true,
    requiredConfigKeys: ["search_engine_id"],
    storedConfigAliases: {
      search_engine_id: ["search_engine_id", "cx", "search_engine"],
    },
  },
  searxng: {
    requiresApiKey: false,
    requiredConfigKeys: ["searxng_base_url"],
    storedConfigAliases: {
      searxng_base_url: ["searxng_base_url"],
    },
  },
};

export function searchProviderRequiresApiKey(
  providerType: WebSearchProviderType
): boolean {
  return SEARCH_PROVIDER_CAPS[providerType].requiresApiKey;
}

export function getStoredConfigValue(
  providerType: WebSearchProviderType,
  canonicalKey: string,
  config: SearchProviderConfig
): string {
  const caps = SEARCH_PROVIDER_CAPS[providerType];
  const aliases = caps.storedConfigAliases?.[canonicalKey] ?? [canonicalKey];

  const safeConfig = config ?? {};
  for (const key of aliases) {
    const value = safeConfig[key];
    if (typeof value === "string" && value.length > 0) {
      return value;
    }
  }
  return "";
}

/** True when the provider has all required credentials/config to be usable. */
export function isSearchProviderConfigured(
  providerType: WebSearchProviderType,
  provider: SearchProviderLike
): boolean {
  const caps = SEARCH_PROVIDER_CAPS[providerType];

  if (caps.requiresApiKey && !(provider?.has_api_key ?? false)) {
    return false;
  }

  for (const requiredKey of caps.requiredConfigKeys) {
    const value = getStoredConfigValue(
      providerType,
      requiredKey,
      provider?.config
    );
    if (!value) {
      return false;
    }
  }

  return true;
}

export function canConnectSearchProvider(
  providerType: WebSearchProviderType,
  apiKey: string,
  searchEngineIdOrBaseUrl: string
): boolean {
  const caps = SEARCH_PROVIDER_CAPS[providerType];

  if (caps.requiresApiKey && apiKey.trim().length === 0) {
    return false;
  }

  // Today, all config-driven search providers only expose a single required string field.
  if (
    caps.requiredConfigKeys.length > 0 &&
    searchEngineIdOrBaseUrl.trim().length === 0
  ) {
    return false;
  }

  return true;
}

/** Build the `config` payload to send to the backend for a provider. */
export function buildSearchProviderConfig(
  providerType: WebSearchProviderType,
  searchEngineIdOrBaseUrl: string
): Record<string, string> {
  const caps = SEARCH_PROVIDER_CAPS[providerType];
  const value = searchEngineIdOrBaseUrl.trim();

  const config: Record<string, string> = {};
  if (!value || caps.requiredConfigKeys.length === 0) {
    return config;
  }

  // Only one required key for now.
  const requiredKey = caps.requiredConfigKeys[0];
  if (!requiredKey) {
    return config;
  }
  config[requiredKey] = value;
  return config;
}

/**
 * For providers that have a single required config field, return that stored value for form prefilling.
 */
export function getSingleConfigFieldValueForForm(
  providerType: WebSearchProviderType,
  provider: SearchProviderLike
): string {
  const caps = SEARCH_PROVIDER_CAPS[providerType];
  if (caps.requiredConfigKeys.length === 0) {
    return "";
  }

  const requiredKey = caps.requiredConfigKeys[0];
  if (!requiredKey) {
    return "";
  }
  return getStoredConfigValue(providerType, requiredKey, provider?.config);
}
