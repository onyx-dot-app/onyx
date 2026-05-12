import {
  SvgBrave,
  SvgExa,
  SvgFirecrawl,
  SvgGoogle,
  SvgSearxng,
  SvgSerper,
} from "@opal/logos";
import { markdown } from "@opal/utils";
import type {
  WebSearchProviderType,
  WebContentProviderType,
  SearchProviderConfig,
  SearchProviderLike,
  ContentProviderConfig,
  ContentProviderLike,
  SearchProviderDetail,
  ContentProviderDetail,
  ConfigFieldSpec,
} from "@/lib/webSearch/types";

// ── Search provider registry ──────────────────────────────────────────────────

export const SEARCH_PROVIDER_DETAILS: Record<
  WebSearchProviderType,
  SearchProviderDetail
> = {
  exa: {
    label: "Exa",
    subtitle: "Exa.ai",
    helper: "Connect to Exa to set up web search.",
    logo: SvgExa,
    apiKeyUrl: "https://dashboard.exa.ai/api-keys",
  },
  serper: {
    label: "Serper",
    subtitle: "Serper.dev",
    helper: "Connect to Serper to set up web search.",
    logo: SvgSerper,
    apiKeyUrl: "https://serper.dev/api-key",
  },
  brave: {
    label: "Brave",
    subtitle: "Brave Search API",
    helper: "Connect to Brave Search API to set up web search.",
    logo: SvgBrave,
    apiKeyUrl:
      "https://api-dashboard.search.brave.com/app/documentation/web-search/get-started",
  },
  google_pse: {
    label: "Google PSE",
    subtitle: "Google",
    helper: "Connect to Google PSE to set up web search.",
    logo: SvgGoogle,
    apiKeyUrl: "https://programmablesearchengine.google.com/controlpanel/all",
  },
  searxng: {
    label: "SearXNG",
    subtitle: "SearXNG",
    helper: "Connect to SearXNG to set up web search.",
    logo: SvgSearxng,
  },
};

export const SEARCH_PROVIDER_ORDER = Object.keys(
  SEARCH_PROVIDER_DETAILS
) as WebSearchProviderType[];

export function getSearchProviderDisplayLabel(
  providerType: string,
  providerName?: string | null
): string {
  if (providerName) return providerName;
  return (
    (SEARCH_PROVIDER_DETAILS as Record<string, SearchProviderDetail>)[
      providerType
    ]?.label ?? providerType
  );
}

export function isBuiltInSearchProviderType(
  providerType: string
): providerType is WebSearchProviderType {
  return Object.prototype.hasOwnProperty.call(
    SEARCH_PROVIDER_DETAILS,
    providerType
  );
}

// ── Search provider capabilities (internal) ───────────────────────────────────

type SearchProviderCapabilities = {
  requiresApiKey: boolean;
  requiredConfigKeys: string[];
  storedConfigAliases?: Record<string, string[]>;
};

const SEARCH_PROVIDER_CAPABILITIES: Record<
  WebSearchProviderType,
  SearchProviderCapabilities
> = {
  exa: { requiresApiKey: true, requiredConfigKeys: [] },
  serper: { requiresApiKey: true, requiredConfigKeys: [] },
  brave: { requiresApiKey: true, requiredConfigKeys: [] },
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
    storedConfigAliases: { searxng_base_url: ["searxng_base_url"] },
  },
};

const DEFAULT_SEARCH_CAPABILITIES: SearchProviderCapabilities = {
  requiresApiKey: true,
  requiredConfigKeys: [],
};

function getSearchCapabilities(
  providerType: string
): SearchProviderCapabilities {
  return (
    (
      SEARCH_PROVIDER_CAPABILITIES as Record<string, SearchProviderCapabilities>
    )[providerType] ?? DEFAULT_SEARCH_CAPABILITIES
  );
}

function getStoredSearchConfigValue(
  providerType: string,
  canonicalKey: string,
  config: SearchProviderConfig
): string {
  const caps = getSearchCapabilities(providerType);
  const aliases = caps.storedConfigAliases?.[canonicalKey] ?? [canonicalKey];
  const safeConfig = config ?? {};
  for (const key of aliases) {
    const value = safeConfig[key];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return "";
}

export function searchProviderRequiresApiKey(providerType: string): boolean {
  return getSearchCapabilities(providerType).requiresApiKey;
}

export function isSearchProviderConfigured(
  providerType: string,
  provider: SearchProviderLike
): boolean {
  const caps = getSearchCapabilities(providerType);
  if (caps.requiresApiKey && !provider?.masked_api_key) return false;
  for (const requiredKey of caps.requiredConfigKeys) {
    if (
      !getStoredSearchConfigValue(providerType, requiredKey, provider?.config)
    )
      return false;
  }
  return true;
}

export function canConnectSearchProvider(
  providerType: string,
  apiKey: string,
  searchEngineIdOrBaseUrl: string
): boolean {
  const caps = getSearchCapabilities(providerType);
  if (caps.requiresApiKey && apiKey.trim().length === 0) return false;
  if (
    caps.requiredConfigKeys.length > 0 &&
    searchEngineIdOrBaseUrl.trim().length === 0
  )
    return false;
  return true;
}

export function buildSearchProviderConfig(
  providerType: string,
  searchEngineIdOrBaseUrl: string
): Record<string, string> {
  const caps = getSearchCapabilities(providerType);
  const value = searchEngineIdOrBaseUrl.trim();
  const config: Record<string, string> = {};
  if (!value || caps.requiredConfigKeys.length === 0) return config;
  const requiredKey = caps.requiredConfigKeys[0];
  if (!requiredKey) return config;
  config[requiredKey] = value;
  return config;
}

export function getSingleConfigFieldValueForForm(
  providerType: string,
  provider: SearchProviderLike
): string {
  const caps = getSearchCapabilities(providerType);
  if (caps.requiredConfigKeys.length === 0) return "";
  const requiredKey = caps.requiredConfigKeys[0];
  if (!requiredKey) return "";
  return getStoredSearchConfigValue(
    providerType,
    requiredKey,
    provider?.config
  );
}

// ── Content provider registry ─────────────────────────────────────────────────

export const CONTENT_PROVIDER_DETAILS: Record<string, ContentProviderDetail> = {
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
    logo: SvgFirecrawl,
  },
  exa: {
    label: "Exa",
    subtitle: "Exa.ai",
    description:
      "Use Exa to fetch and summarize page content from search results.",
    logo: SvgExa,
  },
};

export const CONTENT_PROVIDER_ORDER = Object.keys(
  CONTENT_PROVIDER_DETAILS
) as WebContentProviderType[];

// ── Content provider capabilities (internal) ──────────────────────────────────

type ContentProviderCapabilities = {
  requiresApiKey: boolean;
  requiredConfigKeys: string[];
  storedConfigAliases?: Record<string, string[]>;
};

const CONTENT_PROVIDER_CAPABILITIES: Record<
  string,
  ContentProviderCapabilities
> = {
  onyx_web_crawler: { requiresApiKey: false, requiredConfigKeys: [] },
  firecrawl: {
    requiresApiKey: true,
    requiredConfigKeys: ["base_url"],
    storedConfigAliases: { base_url: ["base_url", "api_base_url"] },
  },
};

const DEFAULT_CONTENT_CAPABILITIES: ContentProviderCapabilities = {
  requiresApiKey: true,
  requiredConfigKeys: [],
};

function getContentCapabilities(
  providerType: WebContentProviderType
): ContentProviderCapabilities {
  return (
    CONTENT_PROVIDER_CAPABILITIES[providerType as string] ??
    DEFAULT_CONTENT_CAPABILITIES
  );
}

function getStoredContentConfigValue(
  providerType: WebContentProviderType,
  canonicalKey: string,
  config: ContentProviderConfig
): string {
  const caps = getContentCapabilities(providerType);
  const aliases = caps.storedConfigAliases?.[canonicalKey] ?? [canonicalKey];
  const safeConfig = config ?? {};
  for (const key of aliases) {
    const value = safeConfig[key];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return "";
}

export function isContentProviderConfigured(
  providerType: WebContentProviderType,
  provider: ContentProviderLike
): boolean {
  const caps = getContentCapabilities(providerType);
  if (caps.requiresApiKey && !provider?.masked_api_key) return false;
  for (const requiredKey of caps.requiredConfigKeys) {
    if (
      !getStoredContentConfigValue(providerType, requiredKey, provider?.config)
    )
      return false;
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
  const caps = getContentCapabilities(providerType);
  const trimmed = baseUrl.trim();
  const config: Record<string, string> = {};
  if (caps.requiredConfigKeys.length === 0 || !trimmed) return config;
  const requiredKey = caps.requiredConfigKeys[0];
  if (!requiredKey) return config;
  config[requiredKey] = trimmed;
  return config;
}

export function canConnectContentProvider(
  providerType: WebContentProviderType,
  apiKey: string,
  baseUrl: string
): boolean {
  const caps = getContentCapabilities(providerType);
  if (caps.requiresApiKey && apiKey.trim().length === 0) return false;
  if (caps.requiredConfigKeys.length > 0 && baseUrl.trim().length === 0)
    return false;
  return true;
}

export function getSingleContentConfigFieldValueForForm(
  providerType: WebContentProviderType,
  provider: ContentProviderLike,
  defaultValue = ""
): string {
  const caps = getContentCapabilities(providerType);
  if (caps.requiredConfigKeys.length === 0) return defaultValue;
  const requiredKey = caps.requiredConfigKeys[0];
  if (!requiredKey) return defaultValue;
  return (
    getStoredContentConfigValue(providerType, requiredKey, provider?.config) ||
    defaultValue
  );
}

// ── Config field specs ────────────────────────────────────────────────────────

export function getSearchConfigField(
  providerType: string
): ConfigFieldSpec | undefined {
  if (providerType === "google_pse") {
    return {
      title: "Search Engine ID",
      placeholder: "Enter your search engine ID",
      subDescription: markdown(
        "Paste your [search engine ID](https://programmablesearchengine.google.com/controlpanel/all) to use for web search."
      ),
    };
  }
  if (providerType === "searxng") {
    return {
      title: "SearXNG Base URL",
      placeholder: "https://your-searxng-instance.com",
      subDescription: markdown(
        "Paste the base URL of your [SearXNG instance](https://docs.searxng.org/admin/installation.html)."
      ),
    };
  }
  return undefined;
}

export function getContentConfigField(
  providerType: string
): ConfigFieldSpec | undefined {
  if (providerType === "firecrawl") {
    return {
      title: "API Base URL",
      placeholder: "https://api.firecrawl.dev/v2/scrape",
      defaultValue: "https://api.firecrawl.dev/v2/scrape",
      subDescription: "Your Firecrawl API base URL.",
    };
  }
  return undefined;
}
