export type WebContentProviderType =
  | "firecrawl"
  | "onyx_web_crawler"
  | (string & {});

export const CONTENT_PROVIDERS_URL = "/api/admin/web-search/content-providers";

export const CONTENT_PROVIDER_DETAILS: Record<
  string,
  { label: string; subtitle: string; description: string; logoSrc?: string }
> = {
  onyx_web_crawler: {
    label: "Onyx Web Crawler",
    subtitle:
      "Built-in web crawler. Works for most pages but less performant in edge cases.",
    description:
      "Onyx's built-in crawler processes URLs returned by your search engine.",
  },
  firecrawl: {
    label: "Firecrawl",
    subtitle: "Leading open-source crawler.",
    description:
      "Connect Firecrawl to fetch and summarize page content from search results.",
    logoSrc: "/firecrawl.svg",
  },
};

/**
 * Display order for built-in providers.
 * Derived from insertion order of `CONTENT_PROVIDER_DETAILS` for a single source of truth.
 */
export const CONTENT_PROVIDER_ORDER = Object.keys(
  CONTENT_PROVIDER_DETAILS
) as WebContentProviderType[];

export type ContentProviderConfig = Record<string, string> | null | undefined;

export type ContentProviderLike =
  | {
      has_api_key: boolean;
      config: ContentProviderConfig;
    }
  | null
  | undefined;

type ContentProviderCapabilities = {
  requiresApiKey: boolean;
  requiredConfigKeys: string[];
  storedConfigAliases?: Record<string, string[]>;
};

const CONTENT_PROVIDER_CAPABILITIES: Record<
  string,
  ContentProviderCapabilities
> = {
  onyx_web_crawler: {
    requiresApiKey: false,
    requiredConfigKeys: [],
  },
  firecrawl: {
    requiresApiKey: true,
    requiredConfigKeys: ["base_url"],
    storedConfigAliases: {
      base_url: ["base_url", "api_base_url"],
    },
  },
};

const DEFAULT_CONTENT_PROVIDER_CAPABILITIES: ContentProviderCapabilities = {
  requiresApiKey: true,
  requiredConfigKeys: [],
};

function getCapabilities(
  providerType: WebContentProviderType
): ContentProviderCapabilities {
  return (
    CONTENT_PROVIDER_CAPABILITIES[providerType as string] ??
    DEFAULT_CONTENT_PROVIDER_CAPABILITIES
  );
}

function getStoredContentConfigValue(
  providerType: WebContentProviderType,
  canonicalKey: string,
  config: ContentProviderConfig
): string {
  const caps = getCapabilities(providerType);
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

export function isContentProviderConfigured(
  providerType: WebContentProviderType,
  provider: ContentProviderLike
): boolean {
  const caps = getCapabilities(providerType);

  if (caps.requiresApiKey && !(provider?.has_api_key ?? false)) {
    return false;
  }

  for (const requiredKey of caps.requiredConfigKeys) {
    const value = getStoredContentConfigValue(
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

export function getCurrentContentProviderType(
  providers: Array<{
    is_active: boolean;
    provider_type: WebContentProviderType;
  }>
): WebContentProviderType {
  return (
    providers.find((p) => p.is_active && p.provider_type !== "onyx_web_crawler")
      ?.provider_type ??
    providers.find((p) => p.is_active)?.provider_type ??
    "onyx_web_crawler"
  );
}

export function buildContentProviderConfig(
  providerType: WebContentProviderType,
  baseUrl: string
): Record<string, string> {
  const caps = getCapabilities(providerType);
  const trimmed = baseUrl.trim();
  const config: Record<string, string> = {};

  if (caps.requiredConfigKeys.length === 0 || !trimmed) {
    return config;
  }

  const requiredKey = caps.requiredConfigKeys[0];
  if (!requiredKey) {
    return config;
  }

  config[requiredKey] = trimmed;
  return config;
}

export function canConnectContentProvider(
  providerType: WebContentProviderType,
  apiKey: string,
  baseUrl: string
): boolean {
  const caps = getCapabilities(providerType);

  if (caps.requiresApiKey && apiKey.trim().length === 0) {
    return false;
  }

  if (caps.requiredConfigKeys.length > 0 && baseUrl.trim().length === 0) {
    return false;
  }

  return true;
}

export function getSingleContentConfigFieldValueForForm(
  providerType: WebContentProviderType,
  provider: ContentProviderLike,
  defaultValue = ""
): string {
  const caps = getCapabilities(providerType);
  if (caps.requiredConfigKeys.length === 0) {
    return defaultValue;
  }

  const requiredKey = caps.requiredConfigKeys[0];
  if (!requiredKey) {
    return defaultValue;
  }

  return (
    getStoredContentConfigValue(providerType, requiredKey, provider?.config) ||
    defaultValue
  );
}
