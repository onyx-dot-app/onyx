"use client";

import Image from "next/image";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AdminPageTitle } from "@/components/admin/Title";
import { CheckmarkIcon, GlobeIcon, InfoIcon } from "@/components/icons/icons";
import Text from "@/refresh-components/texts/Text";
import { Separator } from "@/components/ui/separator";
import useSWR from "swr";
import { errorHandlingFetcher, FetchError } from "@/lib/fetcher";
import { ThreeDotsLoader } from "@/components/Loading";
import { Callout } from "@/components/ui/callout";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import OnyxLogo from "@/icons/onyx-logo";
import SvgKey from "@/icons/key";
import SvgCheckSquare from "@/icons/check-square";
import SvgArrowExchange from "@/icons/arrow-exchange";
import SvgArrowRightCircle from "@/icons/arrow-right-circle";

const CoreModal = dynamic(
  () => import("@/refresh-components/modals/CoreModal"),
  { ssr: false }
);

type WebSearchProviderType = "google_pse" | "serper" | "exa";
type WebContentProviderType = "firecrawl" | "onyx_web_crawler" | (string & {});

interface WebSearchProviderView {
  id: number;
  name: string;
  provider_type: WebSearchProviderType;
  is_active: boolean;
  config: Record<string, string> | null;
  has_api_key: boolean;
}

interface WebContentProviderView {
  id: number;
  name: string;
  provider_type: WebContentProviderType;
  is_active: boolean;
  config: Record<string, string> | null;
  has_api_key: boolean;
}

const SEARCH_PROVIDERS_URL = "/api/admin/web-search/search-providers";
const CONTENT_PROVIDERS_URL = "/api/admin/web-search/content-providers";

const SEARCH_PROVIDER_LABEL: Record<WebSearchProviderType, string> = {
  google_pse: "Google PSE",
  serper: "Serper",
  exa: "Exa",
};

const CONTENT_PROVIDER_LABEL: Record<string, string> = {
  firecrawl: "Firecrawl",
  onyx_web_crawler: "Onyx Web Crawler",
};

const CONTENT_PROVIDER_DETAILS: Record<
  string,
  { subtitle: string; description: string; logoSrc?: string }
> = {
  firecrawl: {
    subtitle: "Leading open-source crawler.",
    description:
      "Connect Firecrawl to fetch and summarize page content from search results.",
    logoSrc: "/firecrawl.svg",
  },
  onyx_web_crawler: {
    subtitle:
      "Built-in web crawler. Works for most pages but less performant in edge cases.",
    description:
      "Onyx’s built-in crawler processes URLs returned by your search engine.",
  },
};

const CONTENT_PROVIDER_ORDER: WebContentProviderType[] = [
  "onyx_web_crawler",
  "firecrawl",
];

const SEARCH_PROVIDER_ORDER: WebSearchProviderType[] = [
  "exa",
  "serper",
  "google_pse",
];

const SEARCH_PROVIDER_DETAILS: Record<
  WebSearchProviderType,
  { subtitle: string; helper: string; logoSrc?: string }
> = {
  exa: {
    subtitle: "Exa.ai",
    helper:
      "Enter credentials for Exa. Onyx stores credentials securely and does not display them after saving.",
    logoSrc: "/Exa.svg",
  },
  serper: {
    subtitle: "Serper.dev",
    helper:
      "Enter credentials for Serper. Onyx stores credentials securely and does not display them after saving.",
    logoSrc: "/Serper.svg",
  },
  google_pse: {
    subtitle: "Google",
    helper:
      "Enter credentials for PSE. Onyx stores credentials securely and does not display them after saving.",
    logoSrc: "/Google.svg",
  },
};

export default function Page() {
  const [selectedProviderType, setSelectedProviderType] =
    useState<WebSearchProviderType | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [apiKeyValue, setApiKeyValue] = useState("");
  const [searchEngineIdValue, setSearchEngineIdValue] = useState("");
  const [selectedContentProviderType, setSelectedContentProviderType] =
    useState<WebContentProviderType | null>(null);
  const [isContentModalOpen, setIsContentModalOpen] = useState(false);
  const [contentApiKeyValue, setContentApiKeyValue] = useState("");
  const [contentBaseUrlValue, setContentBaseUrlValue] = useState("");
  const [isProcessingSearch, setIsProcessingSearch] = useState(false);
  const [searchStatusMessage, setSearchStatusMessage] = useState<string | null>(
    null
  );
  const [searchErrorMessage, setSearchErrorMessage] = useState<string | null>(
    null
  );
  const [isProcessingContent, setIsProcessingContent] = useState(false);
  const [contentStatusMessage, setContentStatusMessage] = useState<
    string | null
  >(null);
  const [contentErrorMessage, setContentErrorMessage] = useState<string | null>(
    null
  );
  const [activatingProviderId, setActivatingProviderId] = useState<
    number | null
  >(null);
  const [activationError, setActivationError] = useState<string | null>(null);
  const [activatingContentProviderId, setActivatingContentProviderId] =
    useState<number | null>(null);
  const [contentActivationError, setContentActivationError] = useState<
    string | null
  >(null);

  const {
    data: searchProvidersData,
    error: searchProvidersError,
    isLoading: isLoadingSearchProviders,
    mutate: mutateSearchProviders,
  } = useSWR<WebSearchProviderView[]>(
    SEARCH_PROVIDERS_URL,
    errorHandlingFetcher
  );

  const {
    data: contentProvidersData,
    error: contentProvidersError,
    isLoading: isLoadingContentProviders,
    mutate: mutateContentProviders,
  } = useSWR<WebContentProviderView[]>(
    CONTENT_PROVIDERS_URL,
    errorHandlingFetcher
  );

  const searchProviders = searchProvidersData ?? [];
  const contentProviders = contentProvidersData ?? [];

  const isLoading = isLoadingSearchProviders || isLoadingContentProviders;

  const prevProviderTypeRef = useRef<WebSearchProviderType | null>(null);
  const wasModalOpenRef = useRef(false);

  useEffect(() => {
    if (!isModalOpen || !selectedProviderType) {
      setApiKeyValue("");
      setSearchEngineIdValue("");
      setSearchStatusMessage(null);
      setSearchErrorMessage(null);
      setIsProcessingSearch(false);
      prevProviderTypeRef.current = null;
      wasModalOpenRef.current = false;
      return;
    }

    const modalJustOpened = !wasModalOpenRef.current;
    const providerChanged =
      prevProviderTypeRef.current !== selectedProviderType;

    if (modalJustOpened || providerChanged) {
      setApiKeyValue("");
      setSearchStatusMessage(null);
      setSearchErrorMessage(null);
    }

    const provider = searchProviders?.find(
      (item) => item.provider_type === selectedProviderType
    );
    if (selectedProviderType === "google_pse") {
      const config = provider?.config || {};
      const searchId =
        config.search_engine_id || config.cx || config.search_engine || "";
      setSearchEngineIdValue(searchId);
    } else {
      setSearchEngineIdValue("");
    }
    prevProviderTypeRef.current = selectedProviderType;
    wasModalOpenRef.current = true;
  }, [isModalOpen, selectedProviderType, searchProviders]);

  useEffect(() => {
    if (!isContentModalOpen || !selectedContentProviderType) {
      setContentApiKeyValue("");
      setContentBaseUrlValue("");
      setContentStatusMessage(null);
      setContentErrorMessage(null);
      setIsProcessingContent(false);
      return;
    }

    // For now Firecrawl credentials are entered fresh each time (we do not expose stored keys).
    setContentApiKeyValue("");
    if (selectedContentProviderType === "firecrawl") {
      const provider = contentProviders?.find(
        (item) => item.provider_type === selectedContentProviderType
      );
      const baseUrl =
        provider?.config?.base_url ||
        provider?.config?.api_base_url ||
        "https://api.firecrawl.dev/v1/scrape";
      setContentBaseUrlValue(baseUrl);
    } else {
      setContentBaseUrlValue("");
    }
  }, [isContentModalOpen, selectedContentProviderType, contentProviders]);

  const hasActiveSearchProvider = searchProviders.some(
    (provider) => provider.is_active
  );

  const searchProvidersByType = useMemo(() => {
    const map = new Map<
      WebSearchProviderType | string,
      WebSearchProviderView
    >();
    searchProviders.forEach((provider) => {
      map.set(provider.provider_type, provider);
    });
    return map;
  }, [searchProviders]);

  type DisplaySearchProvider = {
    key: number | string;
    providerType: WebSearchProviderType | (string & {});
    label: string;
    subtitle: string;
    logoSrc?: string;
    provider?: WebSearchProviderView;
  };

  const orderedSearchProviders: DisplaySearchProvider[] =
    SEARCH_PROVIDER_ORDER.map((providerType) => {
      const provider = searchProvidersByType.get(providerType);
      const label =
        provider?.name || SEARCH_PROVIDER_LABEL[providerType] || providerType;
      const { subtitle, logoSrc } = SEARCH_PROVIDER_DETAILS[providerType];

      return {
        key: provider?.id ?? providerType,
        providerType,
        label,
        subtitle,
        logoSrc,
        provider,
      };
    });

  const additionalSearchProviders = searchProviders.filter(
    (provider) => !SEARCH_PROVIDER_ORDER.includes(provider.provider_type)
  );

  const additionalSearchProviderCards: DisplaySearchProvider[] =
    additionalSearchProviders.map((provider) => {
      const fallbackLabel =
        SEARCH_PROVIDER_LABEL[
          provider.provider_type as WebSearchProviderType
        ] || provider.provider_type;

      return {
        key: provider.id,
        providerType: provider.provider_type,
        label: provider.name || fallbackLabel,
        subtitle: "Custom integration",
        provider,
      };
    });

  const combinedSearchProviders = [
    ...orderedSearchProviders,
    ...additionalSearchProviderCards,
  ];

  const providerLabel = selectedProviderType
    ? SEARCH_PROVIDER_LABEL[selectedProviderType] || selectedProviderType
    : "";
  const trimmedApiKey = apiKeyValue.trim();
  const trimmedSearchEngineId = searchEngineIdValue.trim();
  const canConnect =
    !!selectedProviderType &&
    trimmedApiKey.length > 0 &&
    (selectedProviderType !== "google_pse" || trimmedSearchEngineId.length > 0);
  const contentProviderLabel = selectedContentProviderType
    ? CONTENT_PROVIDER_LABEL[selectedContentProviderType] ||
      selectedContentProviderType
    : "";
  const trimmedContentApiKey = contentApiKeyValue.trim();
  const trimmedContentBaseUrl = contentBaseUrlValue.trim();
  const canConnectContent =
    !!selectedContentProviderType &&
    trimmedContentApiKey.length > 0 &&
    (selectedContentProviderType !== "firecrawl" ||
      trimmedContentBaseUrl.length > 0);

  const renderProviderLogo = (
    logoSrc: string | undefined,
    label: string,
    size = 24,
    isHighlighted = false
  ) =>
    logoSrc ? (
      <Image src={logoSrc} alt={`${label} logo`} width={size} height={size} />
    ) : (
      <GlobeIcon
        size={size}
        className={isHighlighted ? "text-action-text-link-05" : "text-text-02"}
      />
    );

  const renderContentProviderLogo = (
    providerType: string,
    isHighlighted = false,
    size = 28
  ) => {
    if (providerType === "onyx_web_crawler") {
      return (
        <OnyxLogo
          width={size}
          height={size}
          className="text-[#111111] dark:text-[#f5f5f5]"
        />
      );
    }

    if (providerType === "firecrawl") {
      return (
        <Image
          src="/firecrawl.svg"
          alt="Firecrawl logo"
          width={size}
          height={size}
          className="h-7 w-7"
        />
      );
    }

    return <GlobeIcon size={size} className="text-text-02" />;
  };

  const renderKeyBadge = (hasKey: boolean) => (
    <span
      className="flex h-4 w-4 shrink-0 items-center justify-center self-center text-text-03"
      title={hasKey ? "API key stored" : "API key missing"}
      aria-label={hasKey ? "API key stored" : "API key missing"}
    >
      <SvgKey width={16} height={16} className="h-4 w-4 shrink-0" />
    </span>
  );

  const orderedContentProviders = useMemo(() => {
    const existingProviders = new Map<
      WebContentProviderType | string,
      WebContentProviderView
    >();
    contentProviders.forEach((provider) => {
      existingProviders.set(provider.provider_type, provider);
    });

    const ordered = CONTENT_PROVIDER_ORDER.map((providerType) => {
      const provider = existingProviders.get(providerType);
      return provider ?? null;
    }).filter(Boolean) as WebContentProviderView[];

    const additional = contentProviders.filter(
      (provider) => !CONTENT_PROVIDER_ORDER.includes(provider.provider_type)
    );

    return [...ordered, ...additional];
  }, [contentProviders]);

  const displayContentProviders = useMemo(() => {
    const providers = [...orderedContentProviders];
    const hasOnyx = providers.some(
      (provider) => provider.provider_type === "onyx_web_crawler"
    );
    const hasFirecrawl = providers.some(
      (provider) => provider.provider_type === "firecrawl"
    );

    if (!hasOnyx) {
      providers.unshift({
        id: -1,
        name: "Onyx Web Crawler",
        provider_type: "onyx_web_crawler",
        is_active: true,
        config: null,
        has_api_key: true,
      });
    }

    if (!hasFirecrawl) {
      providers.push({
        id: -2,
        name: "Firecrawl",
        provider_type: "firecrawl",
        is_active: false,
        config: null,
        has_api_key: false,
      });
    }

    return providers;
  }, [orderedContentProviders]);

  const currentContentProviderType = useMemo(() => {
    const nonDefaultActive = contentProviders.find(
      (provider) =>
        provider.is_active && provider.provider_type !== "onyx_web_crawler"
    );
    if (nonDefaultActive) return nonDefaultActive.provider_type;

    const anyActive = contentProviders.find((provider) => provider.is_active);
    if (anyActive) return anyActive.provider_type;

    return "onyx_web_crawler";
  }, [contentProviders]);

  if (searchProvidersError || contentProvidersError) {
    const message =
      searchProvidersError?.message ||
      contentProvidersError?.message ||
      "Unable to load web search configuration.";

    const detail =
      (searchProvidersError instanceof FetchError &&
      typeof searchProvidersError.info?.detail === "string"
        ? searchProvidersError.info.detail
        : undefined) ||
      (contentProvidersError instanceof FetchError &&
      typeof contentProvidersError.info?.detail === "string"
        ? contentProvidersError.info.detail
        : undefined);

    return (
      <div className="container mx-auto">
        <AdminPageTitle
          title="Web Search"
          icon={<GlobeIcon size={32} className="my-auto" />}
          includeDivider={false}
        />
        <Callout type="danger" title="Failed to load web search settings">
          {message}
          {detail && (
            <Text className="mt-2 text-text-03" mainContentBody text03>
              {detail}
            </Text>
          )}
        </Callout>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="container mx-auto">
        <AdminPageTitle
          title="Web Search"
          icon={<GlobeIcon size={32} className="my-auto" />}
          includeDivider={false}
        />
        <div className="mt-8">
          <ThreeDotsLoader />
        </div>
      </div>
    );
  }

  const renderCredentialFields = () => {
    if (!selectedProviderType) {
      return null;
    }

    const defaultMessage =
      selectedProviderType === "google_pse"
        ? "Paste your API key from PSE to access your search engine."
        : selectedProviderType === "serper"
          ? "Paste your API key from Serper to access your search engine."
          : "Paste your API key from Exa to access your search engine.";

    let helperMessage = defaultMessage;
    let helperClass = "text-text-03";

    if (searchErrorMessage) {
      helperMessage = searchErrorMessage;
      helperClass = "text-red-500";
    } else if (searchStatusMessage) {
      helperMessage = searchStatusMessage;
      helperClass = searchStatusMessage.toLowerCase().includes("validated")
        ? "text-green-500"
        : "text-text-03";
    } else if (isProcessingSearch) {
      helperMessage = "Validating API key...";
      helperClass = "text-text-03";
    }

    return (
      <div className="flex w-full flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Text mainUiAction text04>
            API Key
          </Text>
          <PasswordInputTypeIn
            placeholder="Enter API key"
            value={apiKeyValue}
            onChange={(event) => setApiKeyValue(event.target.value)}
          />
          <Text mainContentBody text03 className={helperClass}>
            {helperMessage}
          </Text>
        </div>

        {selectedProviderType === "google_pse" && (
          <div className="flex flex-col gap-2">
            <Text mainUiAction text04>
              Search Engine ID
            </Text>
            <InputTypeIn
              placeholder="Enter search engine ID"
              value={searchEngineIdValue}
              onChange={(event) => setSearchEngineIdValue(event.target.value)}
            />
          </div>
        )}
      </div>
    );
  };

  const renderContentCredentialFields = () => {
    if (!selectedContentProviderType) {
      return null;
    }

    const providerName =
      CONTENT_PROVIDER_LABEL[selectedContentProviderType] ||
      selectedContentProviderType;

    const defaultMessage: ReactNode =
      selectedContentProviderType === "firecrawl" ? (
        <>
          Paste your <span className="underline">API key</span> from Firecrawl
          to access your search engine.
        </>
      ) : (
        `Paste your API key from ${providerName} to enable crawling.`
      );

    let helperMessage: ReactNode = defaultMessage;
    let helperClass = "text-text-03";

    if (contentErrorMessage) {
      helperMessage = contentErrorMessage;
      helperClass = "text-red-500";
    } else if (contentStatusMessage) {
      helperMessage = contentStatusMessage;
      helperClass = contentStatusMessage.toLowerCase().includes("validated")
        ? "text-green-500"
        : "text-text-03";
    } else if (isProcessingContent) {
      helperMessage = "Validating API key...";
      helperClass = "text-text-03";
    }

    return (
      <div className="flex w-full flex-col gap-4">
        {selectedContentProviderType === "firecrawl" && (
          <div className="flex flex-col gap-2">
            <Text mainUiAction text04>
              API Base URL
            </Text>
            <InputTypeIn
              placeholder="https://"
              value={contentBaseUrlValue}
              onChange={(event) => setContentBaseUrlValue(event.target.value)}
            />
            <Text mainContentBody text03 className="text-text-03">
              Your Firecrawl API base URL.
            </Text>
          </div>
        )}

        <div className="flex flex-col gap-2">
          <Text mainUiAction text04>
            API Key
          </Text>
          <PasswordInputTypeIn
            placeholder="Enter API key"
            value={contentApiKeyValue}
            onChange={(event) => setContentApiKeyValue(event.target.value)}
          />
          <Text mainContentBody text03 className={helperClass}>
            {helperMessage}
          </Text>
        </div>
      </div>
    );
  };

  const handleSearchConnect = async () => {
    if (!selectedProviderType) {
      return;
    }

    const trimmedKey = trimmedApiKey;
    if (!trimmedKey) {
      return;
    }

    const config: Record<string, string> = {};
    if (selectedProviderType === "google_pse" && trimmedSearchEngineId) {
      config.search_engine_id = trimmedSearchEngineId;
    }

    const existingProvider = searchProviders.find(
      (provider) => provider.provider_type === selectedProviderType
    );

    setIsProcessingSearch(true);
    setSearchErrorMessage(null);
    setSearchStatusMessage("Validating API key...");
    setActivationError(null);

    try {
      const testResponse = await fetch(
        "/api/admin/web-search/search-providers/test",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            provider_type: selectedProviderType,
            api_key: trimmedKey,
            config,
          }),
        }
      );

      if (!testResponse.ok) {
        const errorBody = await testResponse.json().catch(() => ({}));
        throw new Error(
          typeof errorBody?.detail === "string"
            ? errorBody.detail
            : "Failed to validate API key."
        );
      }

      setSearchStatusMessage("API key validated. Activating provider...");

      const payload = {
        id: existingProvider?.id ?? null,
        name:
          existingProvider?.name ??
          SEARCH_PROVIDER_LABEL[selectedProviderType] ??
          selectedProviderType,
        provider_type: selectedProviderType,
        api_key: trimmedKey,
        api_key_changed: true,
        config,
        activate: true,
      };

      const upsertResponse = await fetch(
        "/api/admin/web-search/search-providers",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        }
      );

      if (!upsertResponse.ok) {
        const errorBody = await upsertResponse.json().catch(() => ({}));
        throw new Error(
          typeof errorBody?.detail === "string"
            ? errorBody.detail
            : "Failed to activate provider."
        );
      }

      await mutateSearchProviders();
      setIsModalOpen(false);
      setSelectedProviderType(null);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      setSearchErrorMessage(message);
      setSearchStatusMessage(null);
      setIsProcessingSearch(false);
      return;
    }

    setIsProcessingSearch(false);
  };

  const handleActivateSearchProvider = async (providerId: number) => {
    setActivatingProviderId(providerId);
    setActivationError(null);

    try {
      const response = await fetch(
        `/api/admin/web-search/search-providers/${providerId}/activate`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
        }
      );

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(
          typeof errorBody?.detail === "string"
            ? errorBody.detail
            : "Failed to set provider as default."
        );
      }

      await mutateSearchProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      setActivationError(message);
    } finally {
      setActivatingProviderId(null);
    }
  };

  const handleActivateContentProvider = async (
    provider: WebContentProviderView
  ) => {
    setActivatingContentProviderId(provider.id);
    setContentActivationError(null);

    try {
      if (provider.provider_type === "onyx_web_crawler") {
        const response = await fetch(
          "/api/admin/web-search/content-providers/reset-default",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
          }
        );

        if (!response.ok) {
          const errorBody = await response.json().catch(() => ({}));
          throw new Error(
            typeof errorBody?.detail === "string"
              ? errorBody.detail
              : "Failed to set crawler as default."
          );
        }
      } else if (provider.id > 0) {
        const response = await fetch(
          `/api/admin/web-search/content-providers/${provider.id}/activate`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
          }
        );

        if (!response.ok) {
          const errorBody = await response.json().catch(() => ({}));
          throw new Error(
            typeof errorBody?.detail === "string"
              ? errorBody.detail
              : "Failed to set crawler as default."
          );
        }
      } else {
        const payload = {
          id: null,
          name:
            provider.name ||
            CONTENT_PROVIDER_LABEL[provider.provider_type] ||
            provider.provider_type,
          provider_type: provider.provider_type,
          api_key: null,
          api_key_changed: false,
          config: provider.config ?? null,
          activate: true,
        };

        const response = await fetch(
          "/api/admin/web-search/content-providers",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
          }
        );

        if (!response.ok) {
          const errorBody = await response.json().catch(() => ({}));
          throw new Error(
            typeof errorBody?.detail === "string"
              ? errorBody.detail
              : "Failed to set crawler as default."
          );
        }
      }

      await mutateContentProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      setContentActivationError(message);
    } finally {
      setActivatingContentProviderId(null);
    }
  };

  const handleContentConnect = async () => {
    if (!selectedContentProviderType) {
      return;
    }

    const trimmedKey = trimmedContentApiKey;
    if (!trimmedKey) {
      return;
    }

    const config: Record<string, string> = {};
    if (selectedContentProviderType === "firecrawl" && trimmedContentBaseUrl) {
      config.base_url = trimmedContentBaseUrl;
    }

    const existingProvider = contentProviders.find(
      (provider) => provider.provider_type === selectedContentProviderType
    );

    setIsProcessingContent(true);
    setContentErrorMessage(null);
    setContentStatusMessage("Validating API key...");

    try {
      const testResponse = await fetch(
        "/api/admin/web-search/content-providers/test",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            provider_type: selectedContentProviderType,
            api_key: trimmedKey,
            config,
          }),
        }
      );

      if (!testResponse.ok) {
        const errorBody = await testResponse.json().catch(() => ({}));
        throw new Error(
          typeof errorBody?.detail === "string"
            ? errorBody.detail
            : "Failed to validate API key."
        );
      }

      setContentStatusMessage("API key validated. Activating crawler...");

      const payload = {
        id: existingProvider?.id ?? null,
        name:
          existingProvider?.name ??
          CONTENT_PROVIDER_LABEL[selectedContentProviderType] ??
          selectedContentProviderType,
        provider_type: selectedContentProviderType,
        api_key: trimmedKey,
        api_key_changed: true,
        config,
        activate: true,
      };

      const upsertResponse = await fetch(
        "/api/admin/web-search/content-providers",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        }
      );

      if (!upsertResponse.ok) {
        const errorBody = await upsertResponse.json().catch(() => ({}));
        throw new Error(
          typeof errorBody?.detail === "string"
            ? errorBody.detail
            : "Failed to activate content provider."
        );
      }

      await mutateContentProviders();
      setIsContentModalOpen(false);
      setSelectedContentProviderType(null);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      setContentErrorMessage(message);
      setContentStatusMessage(null);
      setIsProcessingContent(false);
      return;
    }

    setIsProcessingContent(false);
  };

  return (
    <>
      <div className="container mx-auto">
        <AdminPageTitle
          title="Web Search"
          icon={<GlobeIcon size={32} className="my-auto" />}
          includeDivider={false}
        />

        <div className="mt-1 flex w-full max-w-[960px] flex-col gap-3">
          <Text mainContentBody text03 className="text-text-03">
            Search settings for external search across the internet.
          </Text>
          <Separator className="my-0 bg-border-01" />

          <div className="flex flex-col gap-1 self-stretch">
            <Text headingH3 text05>
              Search Engine
            </Text>
            <Text
              className="flex items-start gap-[2px] self-stretch text-text-03"
              mainContentBody
              text03
            >
              External search engine API used for web search result URLs,
              snippets, and metadata.
            </Text>

            {activationError && (
              <Callout type="danger" title="Unable to update default provider">
                {activationError}
              </Callout>
            )}

            {!hasActiveSearchProvider && (
              <div className="flex items-start gap-3 rounded-16 border border-[color:var(--Status-Info-02,#9BBEFF)] bg-[color:var(--Status-Info-00,#F8FAFE)] px-4 py-3">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-[color:var(--Status-Info-01,#D4E4FF)]">
                  <InfoIcon size={16} className="text-[#1D4ED8]" />
                </div>
                <Text
                  className="flex-1"
                  mainContentBody
                  text03
                  style={{ color: "rgba(4, 20, 48, 0.85)" }}
                >
                  Connect a search engine to set up web search.
                </Text>
              </div>
            )}

            <div className="flex flex-col gap-2 self-stretch">
              {combinedSearchProviders.map(
                ({ key, providerType, label, subtitle, logoSrc, provider }) => {
                  const hasStoredKey = provider?.has_api_key ?? false;
                  const isActive = provider?.is_active ?? false;
                  const isHighlighted = isActive;
                  const statusLabel = "";
                  const providerId = provider?.id;
                  const canOpenModal = typeof providerType === "string";

                  const buttonState = (() => {
                    if (!provider || !hasStoredKey) {
                      return {
                        label: "Connect",
                        disabled: false,
                        icon: "arrow" as const,
                        onClick: canOpenModal
                          ? () => {
                              setSelectedProviderType(
                                providerType as WebSearchProviderType
                              );
                              setIsModalOpen(true);
                              setActivationError(null);
                            }
                          : undefined,
                      };
                    }

                    if (isActive) {
                      return {
                        label: "Current Default",
                        disabled: true,
                        icon: "check" as const,
                      };
                    }

                    return {
                      label:
                        activatingProviderId === providerId
                          ? "Setting..."
                          : "Set as Default",
                      disabled: activatingProviderId === providerId,
                      icon: hasStoredKey ? ("arrow-circle" as const) : null,
                      onClick: providerId
                        ? () => {
                            void handleActivateSearchProvider(providerId);
                          }
                        : undefined,
                    };
                  })();

                  return (
                    <div
                      key={`${key}-${providerType}`}
                      className={`flex items-start justify-between gap-3 rounded-16 border px-3.5 py-3 bg-background-neutral-00 dark:bg-background-neutral-00 ${
                        isHighlighted
                          ? "border-action-link-05"
                          : "border-border-01"
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        {renderProviderLogo(logoSrc, label, 24, isHighlighted)}
                        <div className="flex flex-col gap-1">
                          <Text headingH3 text05>
                            {label}
                          </Text>
                          <Text mainContentBody text03 className="text-text-03">
                            {subtitle}
                          </Text>
                        </div>
                      </div>
                      <div className="flex items-center justify-end gap-2">
                        {hasStoredKey && renderKeyBadge(hasStoredKey)}
                        <Button
                          type="button"
                          className={`inline-flex shrink-0 items-center gap-2 rounded-12 px-2 py-2 bg-transparent border-0 shadow-none text-text-02 ${
                            buttonState.icon === "check"
                              ? "text-action-text-link-05"
                              : ""
                          }`}
                          tertiary
                          disabled={
                            buttonState.disabled ||
                            (!buttonState.onClick &&
                              buttonState.icon !== "check")
                          }
                          onClick={buttonState.onClick}
                        >
                          <span className="flex items-center gap-2">
                            <span className="whitespace-nowrap">
                              {buttonState.label}
                            </span>
                            <span className="flex h-4 w-4 items-center justify-center text-current">
                              {buttonState.icon === "check" && (
                                <SvgCheckSquare
                                  width={16}
                                  height={16}
                                  className="h-4 w-4"
                                />
                              )}
                              {buttonState.icon === "arrow" && (
                                <SvgArrowExchange className="h-4 w-4 text-current" />
                              )}
                              {buttonState.icon === "arrow-circle" && (
                                <SvgArrowRightCircle className="h-4 w-4 text-current" />
                              )}
                            </span>
                          </span>
                        </Button>
                      </div>
                    </div>
                  );
                }
              )}
            </div>
          </div>

          <div className="flex flex-col gap-1 self-stretch">
            <Text headingH3 text05>
              Web Crawler
            </Text>
            <Text
              className="flex items-start gap-[2px] self-stretch text-text-03"
              mainContentBody
              text03
            >
              Used to read the full contents of search result pages.
            </Text>

            {contentActivationError && (
              <Callout type="danger" title="Unable to update crawler">
                {contentActivationError}
              </Callout>
            )}

            <div className="flex flex-col gap-2 self-stretch">
              {displayContentProviders.map((provider) => {
                const label =
                  provider.name ||
                  CONTENT_PROVIDER_LABEL[provider.provider_type] ||
                  provider.provider_type;

                const subtitle =
                  CONTENT_PROVIDER_DETAILS[provider.provider_type]?.subtitle ||
                  CONTENT_PROVIDER_LABEL[provider.provider_type] ||
                  provider.provider_type;

                const providerId = provider.id;
                const hasStoredKey =
                  provider.provider_type === "onyx_web_crawler"
                    ? true
                    : provider.has_api_key ?? false;
                const isCurrentCrawler =
                  provider.provider_type === currentContentProviderType;
                const isActivating = activatingContentProviderId === providerId;

                const buttonState = (() => {
                  if (!hasStoredKey) {
                    return {
                      label: "Connect",
                      icon: "arrow" as const,
                      disabled: false,
                      onClick: () => {
                        setSelectedContentProviderType(provider.provider_type);
                        setIsContentModalOpen(true);
                        setContentActivationError(null);
                      },
                    };
                  }

                  if (isCurrentCrawler) {
                    return {
                      label: "Current Crawler",
                      icon: "check" as const,
                      disabled: true,
                    };
                  }

                  const canActivate =
                    providerId > 0 ||
                    provider.provider_type === "onyx_web_crawler";

                  return {
                    label: isActivating ? "Setting..." : "Set as Default",
                    icon: "arrow-circle" as const,
                    disabled: isActivating || !canActivate,
                    onClick: canActivate
                      ? () => {
                          void handleActivateContentProvider(provider);
                        }
                      : undefined,
                  };
                })();

                return (
                  <div
                    key={`${provider.provider_type}-${provider.id}`}
                    className={`flex items-start justify-between gap-3 rounded-16 border px-3.5 py-3 bg-background-neutral-00 dark:bg-background-neutral-00 ${
                      isCurrentCrawler
                        ? "border-action-link-05"
                        : "border-border-01"
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      {renderContentProviderLogo(
                        provider.provider_type,
                        isCurrentCrawler
                      )}
                      <div className="flex flex-col gap-1">
                        <Text headingH3 text05>
                          {label}
                        </Text>
                        <Text mainContentBody text03 className="text-text-03">
                          {subtitle}
                        </Text>
                      </div>
                    </div>
                    <div className="flex items-center justify-end gap-2">
                      {provider.provider_type !== "onyx_web_crawler" &&
                        hasStoredKey &&
                        renderKeyBadge(true)}
                      <Button
                        type="button"
                        className={`inline-flex shrink-0 items-center gap-2 rounded-12 px-2 py-2 bg-transparent border-0 shadow-none ${
                          buttonState.icon === "check"
                            ? "text-action-text-link-05"
                            : "text-text-02"
                        }`}
                        tertiary
                        disabled={
                          buttonState.disabled ||
                          (!buttonState.onClick && buttonState.icon !== "check")
                        }
                        onClick={buttonState.onClick}
                      >
                        <span className="flex items-center gap-2">
                          <span className="whitespace-nowrap">
                            {buttonState.label}
                          </span>
                          <span className="flex h-4 w-4 items-center justify-center text-current">
                            {buttonState.icon === "check" && (
                              <SvgCheckSquare
                                width={16}
                                height={16}
                                className="h-4 w-4"
                              />
                            )}
                            {buttonState.icon === "arrow" && (
                              <SvgArrowExchange className="h-4 w-4 text-current" />
                            )}
                            {buttonState.icon === "arrow-circle" && (
                              <SvgArrowRightCircle className="h-4 w-4 text-current" />
                            )}
                          </span>
                        </span>
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {isModalOpen && selectedProviderType && (
        <CoreModal
          className="w-[480px] max-w-[90vw]"
          onClickOutside={() => {
            setIsModalOpen(false);
            setSelectedProviderType(null);
          }}
        >
          <div className="w-full border-b border-border-01 px-4 pt-4 pb-3 dark:border-border-02">
            <div className="mb-3 flex items-center gap-2.5">
              {renderProviderLogo(
                SEARCH_PROVIDER_DETAILS[selectedProviderType]?.logoSrc,
                providerLabel,
                24
              )}
              <SvgArrowExchange className="h-4 w-4 text-text-02" />
              <OnyxLogo
                width={20}
                height={20}
                className="text-[#0c0c0c] dark:text-text-05"
              />
            </div>
            <Text headingH2 text05 className="tracking-[-0.01em]">
              {`Set up ${providerLabel}`}
            </Text>
          </div>

          <div className="flex w-full flex-col gap-4 px-4 py-4">
            <div className="flex flex-col gap-1.5">
              <Text mainContentBody text03 className="text-text-03">
                {SEARCH_PROVIDER_DETAILS[selectedProviderType]?.subtitle}
              </Text>
              <Text mainContentBody text03 className="text-text-03">
                {SEARCH_PROVIDER_DETAILS[selectedProviderType]?.helper}
              </Text>
            </div>

            <div className="flex max-h-[360px] flex-col gap-4 overflow-y-auto pr-1">
              {renderCredentialFields()}
            </div>
          </div>

          <div className="flex w-full items-center justify-end gap-2 border-t border-border-01 px-4 py-4 dark:border-border-02">
            <Button
              type="button"
              main
              secondary
              className="min-w-[96px]"
              onClick={() => {
                setIsModalOpen(false);
                setSelectedProviderType(null);
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              main
              primary
              className="min-w-[96px]"
              disabled={!canConnect || isProcessingSearch}
              onClick={() => {
                void handleSearchConnect();
              }}
            >
              {isProcessingSearch ? "Connecting..." : "Connect"}
            </Button>
          </div>
        </CoreModal>
      )}

      {isContentModalOpen && selectedContentProviderType && (
        <CoreModal
          className="w-[480px] max-w-[90vw]"
          onClickOutside={() => {
            setIsContentModalOpen(false);
            setSelectedContentProviderType(null);
          }}
        >
          <div className="w-full border-b border-border-01 px-4 pt-4 pb-3 dark:border-border-02">
            <div className="mb-3 flex items-center gap-2.5">
              {renderProviderLogo(
                CONTENT_PROVIDER_DETAILS[selectedContentProviderType]?.logoSrc,
                contentProviderLabel,
                24
              )}
              <SvgArrowExchange className="h-4 w-4 text-text-02" />
              <OnyxLogo
                width={20}
                height={20}
                className="text-[#0c0c0c] dark:text-text-05"
              />
            </div>
            <Text headingH2 text05 className="tracking-[-0.01em]">
              {`Set up ${contentProviderLabel}`}
            </Text>
          </div>

          <div className="flex w-full flex-col gap-4 px-4 py-4">
            <div className="flex flex-col gap-1.5">
              <Text mainContentBody text03 className="text-text-03">
                {CONTENT_PROVIDER_DETAILS[selectedContentProviderType]
                  ?.subtitle || contentProviderLabel}
              </Text>
              <Text mainContentBody text03 className="text-text-03">
                {CONTENT_PROVIDER_DETAILS[selectedContentProviderType]
                  ?.description ||
                  `Provide credentials for ${contentProviderLabel} to enable crawling.`}
              </Text>
            </div>

            <div className="flex max-h-[360px] flex-col gap-4 overflow-y-auto pr-1">
              {renderContentCredentialFields()}
            </div>
          </div>

          <div className="flex w-full items-center justify-end gap-2 border-t border-border-01 px-4 py-4 dark:border-border-02">
            <Button
              type="button"
              main
              secondary
              className="min-w-[96px]"
              onClick={() => {
                setIsContentModalOpen(false);
                setSelectedContentProviderType(null);
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              main
              primary
              className="min-w-[96px]"
              disabled={!canConnectContent || isProcessingContent}
              onClick={() => {
                void handleContentConnect();
              }}
            >
              {isProcessingContent ? "Connecting..." : "Connect"}
            </Button>
          </div>
        </CoreModal>
      )}
    </>
  );
}
