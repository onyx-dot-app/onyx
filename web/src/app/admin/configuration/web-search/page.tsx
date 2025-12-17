"use client";

import Image from "next/image";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  memo,
} from "react";
import { AdminPageTitle } from "@/components/admin/Title";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { GlobeIcon, InfoIcon } from "@/components/icons/icons";
import Text from "@/refresh-components/texts/Text";
import Separator from "@/refresh-components/Separator";
import useSWR from "swr";
import { errorHandlingFetcher, FetchError } from "@/lib/fetcher";
import { ThreeDotsLoader } from "@/components/Loading";
import { Callout } from "@/components/ui/callout";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { FormField } from "@/refresh-components/form/FormField";
import {
  SvgArrowExchange,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgGlobe,
  SvgKey,
  SvgOnyxLogo,
  SvgX,
} from "@opal/icons";

import Modal from "@/refresh-components/Modal";
import type { IconProps } from "@opal/types";

type WebSearchProviderType = "google_pse" | "serper" | "exa" | "searxng";
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
  searxng: "SearXNG",
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
  "searxng",
];

const SEARCH_PROVIDER_DETAILS: Record<
  WebSearchProviderType,
  { subtitle: string; helper: string; logoSrc?: string; apiKeyUrl?: string }
> = {
  exa: {
    subtitle: "Exa.ai",
    helper: "Connect to Exa to set up web search.",
    logoSrc: "/Exa.svg",
    apiKeyUrl: "https://dashboard.exa.ai/api-keys",
  },
  serper: {
    subtitle: "Serper.dev",
    helper: "Connect to Serper to set up web search.",
    logoSrc: "/Serper.svg",
    apiKeyUrl: "https://serper.dev/api-key",
  },
  google_pse: {
    subtitle: "Google",
    helper: "Connect to Google PSE to set up web search.",
    logoSrc: "/Google.svg",
    apiKeyUrl: "https://programmablesearchengine.google.com/controlpanel/all",
  },
  searxng: {
    subtitle: "SearXNG",
    helper: "Connect to SearXNG to set up web search.",
    logoSrc: "/SearXNG.svg",
  },
};

type ProviderSetupModalProps = {
  isOpen: boolean;
  onClose: () => void;
  providerLabel: string;
  providerLogo: ReactNode;
  description: string;
  apiKeyValue: string;
  onApiKeyChange: (value: string) => void;
  optionalField?: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
    description?: ReactNode;
    showFirst?: boolean;
  };
  helperMessage: ReactNode;
  helperClass: string;
  isProcessing: boolean;
  canConnect: boolean;
  onConnect: () => void;
  apiKeyAutoFocus?: boolean;
  hideApiKey?: boolean;
};

const ProviderSetupModal = memo(
  ({
    isOpen,
    onClose,
    providerLabel,
    providerLogo,
    description,
    apiKeyValue,
    onApiKeyChange,
    optionalField,
    helperMessage,
    helperClass,
    isProcessing,
    canConnect,
    onConnect,
    apiKeyAutoFocus = true,
    hideApiKey = false,
  }: ProviderSetupModalProps) => {
    // Create a custom icon component that renders the provider logo arrangement
    const LogoArrangement = useMemo(() => {
      const Component: React.FunctionComponent<IconProps> = () => (
        <div className="flex items-center gap-1">
          {providerLogo}
          <div className="flex items-center justify-center size-4 p-0.5 shrink-0">
            <SvgArrowExchange className="size-3 text-text-04" />
          </div>
          <div className="flex items-center justify-center size-7 p-0.5 shrink-0 overflow-clip">
            <SvgOnyxLogo
              width={24}
              height={24}
              className="text-text-04 shrink-0"
            />
          </div>
        </div>
      );
      return Component;
    }, [providerLogo]);

    return (
      <Modal open={isOpen} onOpenChange={(open) => !open && onClose()}>
        <Modal.Content mini preventAccidentalClose={true}>
          <Modal.Header
            icon={LogoArrangement}
            title={`Set up ${providerLabel}`}
            description={description}
            onClose={onClose}
          />
          <Modal.Body className="bg-background-tint-01 overflow-y-auto max-h-[512px]">
            {optionalField?.showFirst && (
              <FormField
                name={optionalField.label.toLowerCase().replace(/\s+/g, "_")}
                state="idle"
                className="w-full"
              >
                <FormField.Label>{optionalField.label}</FormField.Label>
                <FormField.Control asChild>
                  <InputTypeIn
                    placeholder={optionalField.placeholder}
                    value={optionalField.value}
                    onChange={(event) =>
                      optionalField.onChange(event.target.value)
                    }
                  />
                </FormField.Control>
                {optionalField.description && (
                  <FormField.Description>
                    {optionalField.description}
                  </FormField.Description>
                )}
              </FormField>
            )}

            <FormField
              name="api_key"
              state={
                helperClass.includes("status-error") ||
                helperClass.includes("error")
                  ? "error"
                  : helperClass.includes("green")
                    ? "success"
                    : "idle"
              }
              className="w-full"
            >
              <FormField.Label>API Key</FormField.Label>
              <FormField.Control asChild>
                <PasswordInputTypeIn
                  placeholder="Enter API key"
                  value={apiKeyValue}
                  autoFocus={apiKeyAutoFocus}
                  onFocus={(e) => {
                    // Select all text if it's the masked placeholder when focused
                    if (apiKeyValue === "••••••••••••••••") {
                      e.target.select();
                    }
                  }}
                  onChange={(event) => {
                    onApiKeyChange(event.target.value);
                  }}
                  showClearButton={false}
                />
              </FormField.Control>
              {isProcessing ? (
                <FormField.APIMessage
                  state="loading"
                  messages={{
                    loading:
                      typeof helperMessage === "string"
                        ? helperMessage
                        : "Validating API key...",
                  }}
                />
              ) : typeof helperMessage === "string" ? (
                <FormField.Message
                  messages={{
                    idle:
                      helperClass.includes("status-error") ||
                      helperClass.includes("error")
                        ? ""
                        : helperClass.includes("green")
                          ? ""
                          : helperMessage,
                    error:
                      helperClass.includes("status-error") ||
                      helperClass.includes("error")
                        ? helperMessage
                        : "",
                    success: helperClass.includes("green") ? helperMessage : "",
                  }}
                />
              ) : (
                <FormField.Description className={helperClass}>
                  {helperMessage}
                </FormField.Description>
              )}
            </FormField>

            {optionalField && !optionalField.showFirst && (
              <FormField
                name={optionalField.label.toLowerCase().replace(/\s+/g, "_")}
                state={
                  hideApiKey &&
                  (helperClass.includes("status-error") ||
                    helperClass.includes("error"))
                    ? "error"
                    : "idle"
                }
                className="w-full"
              >
                <FormField.Label>{optionalField.label}</FormField.Label>
                <FormField.Control asChild>
                  <InputTypeIn
                    placeholder={optionalField.placeholder}
                    value={optionalField.value}
                    onChange={(event) =>
                      optionalField.onChange(event.target.value)
                    }
                  />
                </FormField.Control>
                {optionalField.description && (
                  <FormField.Description>
                    {optionalField.description}
                  </FormField.Description>
                )}
                {hideApiKey && (
                  <>
                    {isProcessing ? (
                      <FormField.APIMessage
                        state="loading"
                        messages={{
                          loading:
                            typeof helperMessage === "string"
                              ? helperMessage
                              : "Testing connection...",
                        }}
                      />
                    ) : typeof helperMessage === "string" ? (
                      <FormField.Message
                        messages={{
                          idle:
                            helperClass.includes("status-error") ||
                            helperClass.includes("error")
                              ? ""
                              : helperClass.includes("green")
                                ? ""
                                : "",
                          error:
                            helperClass.includes("status-error") ||
                            helperClass.includes("error")
                              ? helperMessage
                              : "",
                          success: helperClass.includes("green")
                            ? helperMessage
                            : "",
                        }}
                      />
                    ) : null}
                  </>
                )}
                {hideApiKey && (
                  <>
                    {isProcessing ? (
                      <FormField.APIMessage
                        state="loading"
                        messages={{
                          loading:
                            typeof helperMessage === "string"
                              ? helperMessage
                              : "Testing connection...",
                        }}
                      />
                    ) : typeof helperMessage === "string" ? (
                      <FormField.Message
                        messages={{
                          idle:
                            helperClass.includes("status-error") ||
                            helperClass.includes("error")
                              ? ""
                              : helperClass.includes("green")
                                ? ""
                                : "",
                          error:
                            helperClass.includes("status-error") ||
                            helperClass.includes("error")
                              ? helperMessage
                              : "",
                          success: helperClass.includes("green")
                            ? helperMessage
                            : "",
                        }}
                      />
                    ) : null}
                  </>
                )}
              </FormField>
            )}
          </Modal.Body>
          <Modal.Footer className="gap-2">
            <Button type="button" main secondary onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="button"
              main
              primary
              disabled={!canConnect || isProcessing}
              onClick={onConnect}
            >
              {isProcessing ? "Connecting..." : "Connect"}
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    );
  }
);

ProviderSetupModal.displayName = "ProviderSetupModal";

const HoverIconButton = ({
  isHovered,
  onMouseEnter,
  onMouseLeave,
  children,
  ...buttonProps
}: {
  isHovered: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  children: React.ReactNode;
} & React.ComponentProps<typeof Button>) => {
  return (
    <div onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}>
      <Button {...buttonProps} rightIcon={isHovered ? SvgX : SvgCheckSquare}>
        {children}
      </Button>
    </div>
  );
};

export default function Page() {
  const [selectedProviderType, setSelectedProviderType] =
    useState<WebSearchProviderType | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [apiKeyValue, setApiKeyValue] = useState("");
  const [apiKeyChanged, setApiKeyChanged] = useState(false);
  const [searchEngineIdValue, setSearchEngineIdValue] = useState("");
  const [selectedContentProviderType, setSelectedContentProviderType] =
    useState<WebContentProviderType | null>(null);
  const [isContentModalOpen, setIsContentModalOpen] = useState(false);
  const [contentApiKeyValue, setContentApiKeyValue] = useState("");
  const [contentApiKeyChanged, setContentApiKeyChanged] = useState(false);
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
  const [hoveredButtonKey, setHoveredButtonKey] = useState<string | null>(null);

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
      setApiKeyChanged(false);
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

    const provider = searchProviders?.find(
      (item) => item.provider_type === selectedProviderType
    );

    if (modalJustOpened || providerChanged) {
      // If there's a stored key, show a masked placeholder
      if (provider?.has_api_key) {
        setApiKeyValue("••••••••••••••••");
        setApiKeyChanged(false);
      } else {
        setApiKeyValue("");
        setApiKeyChanged(true); // New provider, any input is a change
      }
      setSearchStatusMessage(null);
      setSearchErrorMessage(null);
    }
    if (
      selectedProviderType === "google_pse" ||
      selectedProviderType === "searxng"
    ) {
      const config = provider?.config || {};
      const searchId =
        config.search_engine_id ||
        config.cx ||
        config.search_engine ||
        config.searxng_base_url ||
        "";
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
      setContentApiKeyChanged(false);
      setContentBaseUrlValue("");
      setContentStatusMessage(null);
      setContentErrorMessage(null);
      setIsProcessingContent(false);
      return;
    }

    const provider = contentProviders?.find(
      (item) => item.provider_type === selectedContentProviderType
    );

    // If there's a stored key, show a masked placeholder
    if (provider?.has_api_key) {
      setContentApiKeyValue("••••••••••••••••");
      setContentApiKeyChanged(false);
    } else {
      setContentApiKeyValue("");
      setContentApiKeyChanged(true); // New provider, any input is a change
    }

    if (selectedContentProviderType === "firecrawl") {
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

  const hasStoredApiKey = searchProviders.some(
    (provider) => provider.has_api_key
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
  // To connect, we must specify a provider type. We  also must specify an API key
  // for all providers except SearXNG, and an identifier for the search engine for
  // SearXNG and Google PSE.
  const canConnect =
    !!selectedProviderType &&
    (selectedProviderType === "searxng" || trimmedApiKey.length > 0) &&
    ((selectedProviderType !== "google_pse" &&
      selectedProviderType !== "searxng") ||
      trimmedSearchEngineId.length > 0);
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
    size = 16,
    isHighlighted = false,
    containerSize?: number
  ) => {
    const containerSizeClass =
      size === 24 || containerSize === 28 ? "size-7" : "size-5";

    return (
      <div
        className={`flex items-center justify-center ${containerSizeClass} px-0.5 py-0 shrink-0 overflow-clip`}
      >
        {logoSrc ? (
          <Image
            src={logoSrc}
            alt={`${label} logo`}
            width={size}
            height={size}
          />
        ) : (
          <SvgGlobe
            size={size}
            className={
              isHighlighted ? "text-action-text-link-05" : "text-text-02"
            }
          />
        )}
      </div>
    );
  };

  const renderContentProviderLogo = (
    providerType: string,
    isHighlighted = false,
    size = 16,
    containerSize?: number
  ) => {
    const logoContent =
      providerType === "onyx_web_crawler" ? (
        <SvgOnyxLogo
          width={size}
          height={size}
          className="text-[#111111] dark:text-[#f5f5f5]"
        />
      ) : providerType === "firecrawl" ? (
        <Image
          src="/firecrawl.svg"
          alt="Firecrawl logo"
          width={size}
          height={size}
        />
      ) : (
        <SvgGlobe size={size} className="text-text-02" />
      );

    const containerSizeClass =
      size === 24 || containerSize === 28 ? "size-7" : "size-5";

    return (
      <div
        className={`flex items-center justify-center ${containerSizeClass} px-0.5 py-0 shrink-0 overflow-clip`}
      >
        {logoContent}
      </div>
    );
  };

  const renderKeyBadge = (hasKey: boolean, onClick?: () => void) => {
    const baseClasses =
      "flex h-4 w-4 shrink-0 items-center justify-center self-center text-text-03";
    const clickableClasses = onClick
      ? "cursor-pointer hover:text-text-01 transition-colors"
      : "";

    const content = (
      <SvgKey width={16} height={16} className="h-4 w-4 shrink-0" />
    );

    if (onClick) {
      return (
        <button
          type="button"
          onClick={onClick}
          className={`${baseClasses} ${clickableClasses}`}
          title="Click to update API key"
          aria-label="Click to update API key"
        >
          {content}
        </button>
      );
    }

    return (
      <span
        className={baseClasses}
        title={hasKey ? "API key stored" : "API key missing"}
        aria-label={hasKey ? "API key stored" : "API key missing"}
      >
        {content}
      </span>
    );
  };

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
          icon={SvgGlobe}
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
          icon={SvgGlobe}
          includeDivider={false}
        />
        <div className="mt-8">
          <ThreeDotsLoader />
        </div>
      </div>
    );
  }

  const getSearchProviderHelperMessage = () => {
    if (searchErrorMessage) {
      return searchErrorMessage;
    }
    if (searchStatusMessage) {
      return searchStatusMessage;
    }
    if (isProcessingSearch) {
      return selectedProviderType === "searxng"
        ? "Checking connection..."
        : "Validating API key...";
    }

    const providerDetails = selectedProviderType
      ? SEARCH_PROVIDER_DETAILS[selectedProviderType]
      : null;
    const apiKeyUrl = providerDetails?.apiKeyUrl || "#";

    return (
      <>
        Paste your{" "}
        <a
          href={apiKeyUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          API key
        </a>{" "}
        {selectedProviderType === "google_pse"
          ? "from PSE"
          : selectedProviderType === "serper"
            ? "from Serper"
            : "from Exa"}{" "}
        to access your search engine.
      </>
    );
  };

  const getSearchProviderHelperClass = () => {
    if (searchErrorMessage) return "text-status-error-05";
    if (searchStatusMessage) {
      return searchStatusMessage.toLowerCase().includes("validated")
        ? "text-green-500"
        : "text-text-03";
    }
    return "text-text-03";
  };

  const handleSearchConnect = async () => {
    if (!selectedProviderType) {
      return;
    }

    const trimmedKey = trimmedApiKey;
    if (selectedProviderType !== "searxng" && !trimmedKey) {
      return;
    }

    const config: Record<string, string> = {};
    if (selectedProviderType === "google_pse" && trimmedSearchEngineId) {
      config.search_engine_id = trimmedSearchEngineId;
    }
    if (selectedProviderType === "searxng" && trimmedSearchEngineId) {
      config.searxng_base_url = trimmedSearchEngineId;
    }

    const existingProvider = searchProviders.find(
      (provider) => provider.provider_type === selectedProviderType
    );

    // Check if config changed from stored values
    const storedConfig = existingProvider?.config || {};
    const configChanged =
      selectedProviderType === "google_pse" &&
      (storedConfig.search_engine_id || storedConfig.cx || "") !==
        trimmedSearchEngineId;

    // Determine if validation is needed (new provider, API key changed, or config changed)
    const needsValidation =
      !existingProvider?.has_api_key || apiKeyChanged || configChanged;

    // For new providers, we must have an API key
    if (!existingProvider?.has_api_key && !trimmedKey) {
      return;
    }

    // If API key changed, we need the new key
    if (apiKeyChanged && !trimmedKey) {
      return;
    }

    setIsProcessingSearch(true);
    setSearchErrorMessage(null);
    setActivationError(null);

    try {
      // Validate if needed (new provider, API key changed, or config changed)
      if (needsValidation) {
        setSearchStatusMessage("Validating configuration...");
        const testResponse = await fetch(
          "/api/admin/web-search/search-providers/test",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              provider_type: selectedProviderType,
              // Send API key if changed, otherwise use stored key
              api_key: apiKeyChanged ? trimmedKey : null,
              use_stored_key: !apiKeyChanged && existingProvider?.has_api_key,
              config,
            }),
          }
        );

        if (!testResponse.ok) {
          const errorBody = await testResponse.json().catch(() => ({}));
          throw new Error(
            typeof errorBody?.detail === "string"
              ? errorBody.detail
              : "Failed to validate configuration."
          );
        }

        setSearchStatusMessage(
          "Configuration validated. Activating provider..."
        );
      } else {
        setSearchStatusMessage("Activating provider...");
      }

      const payload = {
        id: existingProvider?.id ?? null,
        name:
          existingProvider?.name ??
          SEARCH_PROVIDER_LABEL[selectedProviderType] ??
          selectedProviderType,
        provider_type: selectedProviderType,
        api_key: apiKeyChanged ? trimmedKey : null,
        api_key_changed: apiKeyChanged,
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

  const handleDeactivateSearchProvider = async (providerId: number) => {
    setActivatingProviderId(providerId);
    setActivationError(null);

    try {
      const response = await fetch(
        `/api/admin/web-search/search-providers/${providerId}/deactivate`,
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
            : "Failed to deactivate provider."
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

  const handleDeactivateContentProvider = async (
    providerId: number,
    providerType: string
  ) => {
    setActivatingContentProviderId(providerId);
    setContentActivationError(null);

    try {
      // For onyx_web_crawler (virtual provider with id -1), use reset-default
      // For real providers, use the deactivate endpoint
      const endpoint =
        providerType === "onyx_web_crawler" || providerId < 0
          ? "/api/admin/web-search/content-providers/reset-default"
          : `/api/admin/web-search/content-providers/${providerId}/deactivate`;

      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(
          typeof errorBody?.detail === "string"
            ? errorBody.detail
            : "Failed to deactivate provider."
        );
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

  const getContentProviderHelperMessage = () => {
    if (contentErrorMessage) {
      return contentErrorMessage;
    }
    if (contentStatusMessage) {
      return contentStatusMessage;
    }
    if (isProcessingContent) {
      return "Validating API key...";
    }

    const providerName = selectedContentProviderType
      ? CONTENT_PROVIDER_LABEL[selectedContentProviderType] ||
        selectedContentProviderType
      : "";

    return selectedContentProviderType === "firecrawl" ? (
      <>
        Paste your <span className="underline">API key</span> from Firecrawl to
        access your search engine.
      </>
    ) : (
      `Paste your API key from ${providerName} to enable crawling.`
    );
  };

  const getContentProviderHelperClass = () => {
    if (contentErrorMessage) return "text-status-error-05";
    if (contentStatusMessage) {
      return contentStatusMessage.toLowerCase().includes("validated")
        ? "text-green-500"
        : "text-text-03";
    }
    return "text-text-03";
  };

  const handleContentConnect = async () => {
    if (!selectedContentProviderType) {
      return;
    }

    const trimmedKey = trimmedContentApiKey;
    const config: Record<string, string> = {};
    if (selectedContentProviderType === "firecrawl" && trimmedContentBaseUrl) {
      config.base_url = trimmedContentBaseUrl;
    }

    const existingProvider = contentProviders.find(
      (provider) => provider.provider_type === selectedContentProviderType
    );

    // Check if config changed from stored values
    const storedConfig = existingProvider?.config || {};
    const storedBaseUrl =
      storedConfig.base_url ||
      storedConfig.api_base_url ||
      "https://api.firecrawl.dev/v1/scrape";
    const configChanged =
      selectedContentProviderType === "firecrawl" &&
      storedBaseUrl !== trimmedContentBaseUrl;

    // Determine if validation is needed (new provider, API key changed, or config changed)
    const needsValidation =
      !existingProvider?.has_api_key || contentApiKeyChanged || configChanged;

    // For new providers, we must have an API key
    if (!existingProvider?.has_api_key && !trimmedKey) {
      return;
    }

    // If API key changed, we need the new key
    if (contentApiKeyChanged && !trimmedKey) {
      return;
    }

    setIsProcessingContent(true);
    setContentErrorMessage(null);

    try {
      // Validate if needed (new provider, API key changed, or config changed)
      if (needsValidation) {
        setContentStatusMessage("Validating configuration...");
        const testResponse = await fetch(
          "/api/admin/web-search/content-providers/test",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              provider_type: selectedContentProviderType,
              // Send API key if changed, otherwise use stored key
              api_key: contentApiKeyChanged ? trimmedKey : null,
              use_stored_key:
                !contentApiKeyChanged && existingProvider?.has_api_key,
              config,
            }),
          }
        );

        if (!testResponse.ok) {
          const errorBody = await testResponse.json().catch(() => ({}));
          throw new Error(
            typeof errorBody?.detail === "string"
              ? errorBody.detail
              : "Failed to validate configuration."
          );
        }

        setContentStatusMessage(
          "Configuration validated. Activating crawler..."
        );
      } else {
        setContentStatusMessage("Activating crawler...");
      }

      const payload = {
        id: existingProvider?.id ?? null,
        name:
          existingProvider?.name ??
          CONTENT_PROVIDER_LABEL[selectedContentProviderType] ??
          selectedContentProviderType,
        provider_type: selectedContentProviderType,
        api_key: contentApiKeyChanged ? trimmedKey : null,
        api_key_changed: contentApiKeyChanged,
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
        <div className="w-full">
          <div className="mb-4">
            <HealthCheckBanner />
          </div>
          <div className="w-full flex flex-col gap-0.5 px-4">
            <Text headingH2 text04 className="flex gap-x-2 items-center">
              <GlobeIcon size={32} className="my-auto" /> Web Search
            </Text>
            <Text secondaryBody text03 className="px-0.5">
              Search settings for external search across the internet.
            </Text>
          </div>
        </div>

        <div className="mt-1 flex w-full max-w-[960px] flex-col gap-8 px-4 py-6">
          <Separator className="py-0" />

          <div className="flex flex-col gap-3 self-stretch">
            <div className="flex flex-col gap-0.5">
              <Text mainContentEmphasis text05>
                Search Engine
              </Text>
              <Text
                className="flex items-start gap-[2px] self-stretch text-text-03"
                secondaryBody
                text03
              >
                External search engine API used for web search result URLs,
                snippets, and metadata.
              </Text>
            </div>

            {activationError && (
              <Callout type="danger" title="Unable to update default provider">
                {activationError}
              </Callout>
            )}

            {!hasActiveSearchProvider && (
              <div
                className="flex items-start rounded-16 border p-1"
                style={{
                  backgroundColor: "var(--status-info-00)",
                  borderColor: "var(--status-info-02)",
                }}
              >
                <div className="flex items-start gap-1 p-2">
                  <div
                    className="flex size-5 items-center justify-center rounded-full p-0.5"
                    style={{
                      backgroundColor: "var(--status-info-01)",
                    }}
                  >
                    <div style={{ color: "var(--status-text-info-05)" }}>
                      <InfoIcon size={16} />
                    </div>
                  </div>
                  <Text className="flex-1 px-0.5" mainUiBody text04>
                    {hasStoredApiKey
                      ? "Select a search engine to enable web search."
                      : "Connect a search engine to set up web search."}
                  </Text>
                </div>
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
                        disabled: false,
                        icon: "check" as const,
                        onClick: providerId
                          ? () => {
                              void handleDeactivateSearchProvider(providerId);
                            }
                          : undefined,
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

                  const buttonKey = `search-${key}-${providerType}`;
                  const isButtonHovered = hoveredButtonKey === buttonKey;
                  const isCardClickable =
                    buttonState.icon === "arrow" &&
                    typeof buttonState.onClick === "function" &&
                    !buttonState.disabled;

                  const handleCardClick = () => {
                    if (isCardClickable) {
                      buttonState.onClick?.();
                    }
                  };

                  return (
                    <div
                      key={`${key}-${providerType}`}
                      onClick={isCardClickable ? handleCardClick : undefined}
                      className={`flex items-start justify-between gap-3 rounded-16 border p-1 bg-background-neutral-00 dark:bg-background-neutral-00 ${
                        isHighlighted
                          ? "border-action-link-05"
                          : "border-border-01"
                      } ${
                        isCardClickable
                          ? "cursor-pointer hover:bg-background-tint-01 transition-colors"
                          : ""
                      }`}
                    >
                      <div className="flex flex-1 items-start gap-1 px-2 py-1">
                        {renderProviderLogo(logoSrc, label, 16, isHighlighted)}
                        <div className="flex flex-col gap-0.5">
                          <Text mainUiAction text05>
                            {label}
                          </Text>
                          <Text secondaryBody text03>
                            {subtitle}
                          </Text>
                        </div>
                      </div>
                      <div className="flex items-center justify-end gap-2">
                        {hasStoredKey &&
                          renderKeyBadge(hasStoredKey, () => {
                            if (
                              typeof providerType === "string" &&
                              (providerType === "google_pse" ||
                                providerType === "serper" ||
                                providerType === "exa" ||
                                providerType === "searxng")
                            ) {
                              setSelectedProviderType(
                                providerType as WebSearchProviderType
                              );
                              setIsModalOpen(true);
                              setSearchStatusMessage(null);
                              setSearchErrorMessage(null);
                            }
                          })}
                        {buttonState.icon === "check" ? (
                          <HoverIconButton
                            isHovered={isButtonHovered}
                            onMouseEnter={() => setHoveredButtonKey(buttonKey)}
                            onMouseLeave={() => setHoveredButtonKey(null)}
                            action={true}
                            tertiary
                            disabled={buttonState.disabled}
                            onClick={(e) => {
                              e.stopPropagation();
                              buttonState.onClick?.();
                            }}
                          >
                            {buttonState.label}
                          </HoverIconButton>
                        ) : (
                          <Button
                            action={false}
                            tertiary
                            disabled={
                              buttonState.disabled || !buttonState.onClick
                            }
                            onClick={(e) => {
                              e.stopPropagation();
                              buttonState.onClick?.();
                            }}
                            rightIcon={
                              buttonState.icon === "arrow"
                                ? SvgArrowExchange
                                : buttonState.icon === "arrow-circle"
                                  ? SvgArrowRightCircle
                                  : undefined
                            }
                          >
                            {buttonState.label}
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                }
              )}
            </div>
          </div>

          <div className="flex flex-col gap-3 self-stretch">
            <div className="flex flex-col gap-0.5">
              <Text mainContentEmphasis text05>
                Web Crawler
              </Text>
              <Text
                className="flex items-start gap-[2px] self-stretch text-text-03"
                secondaryBody
                text03
              >
                Used to read the full contents of search result pages.
              </Text>
            </div>

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
                      disabled: false,
                      onClick: () => {
                        void handleDeactivateContentProvider(
                          providerId,
                          provider.provider_type
                        );
                      },
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

                const contentButtonKey = `content-${provider.provider_type}-${provider.id}`;
                const isContentButtonHovered =
                  hoveredButtonKey === contentButtonKey;
                const isContentCardClickable =
                  buttonState.icon === "arrow" &&
                  typeof buttonState.onClick === "function" &&
                  !buttonState.disabled;

                const handleContentCardClick = () => {
                  if (isContentCardClickable) {
                    buttonState.onClick?.();
                  }
                };

                return (
                  <div
                    key={`${provider.provider_type}-${provider.id}`}
                    onClick={
                      isContentCardClickable
                        ? handleContentCardClick
                        : undefined
                    }
                    className={`flex items-start justify-between gap-3 rounded-16 border p-1 bg-background-neutral-00 dark:bg-background-neutral-00 ${
                      isCurrentCrawler
                        ? "border-action-link-05"
                        : "border-border-01"
                    } ${
                      isContentCardClickable
                        ? "cursor-pointer hover:bg-background-tint-01 transition-colors"
                        : ""
                    }`}
                  >
                    <div className="flex flex-1 items-start gap-1 px-2 py-1">
                      {renderContentProviderLogo(
                        provider.provider_type,
                        isCurrentCrawler
                      )}
                      <div className="flex flex-col gap-0.5">
                        <Text mainUiAction text05>
                          {label}
                        </Text>
                        <Text secondaryBody text03>
                          {subtitle}
                        </Text>
                      </div>
                    </div>
                    <div className="flex items-center justify-end gap-2">
                      {provider.provider_type !== "onyx_web_crawler" &&
                        hasStoredKey &&
                        renderKeyBadge(true, () => {
                          setSelectedContentProviderType(
                            provider.provider_type
                          );
                          setIsContentModalOpen(true);
                          setContentStatusMessage(null);
                          setContentErrorMessage(null);
                        })}
                      {buttonState.icon === "check" ? (
                        <HoverIconButton
                          isHovered={isContentButtonHovered}
                          onMouseEnter={() =>
                            setHoveredButtonKey(contentButtonKey)
                          }
                          onMouseLeave={() => setHoveredButtonKey(null)}
                          action={true}
                          tertiary
                          disabled={buttonState.disabled}
                          onClick={(e) => {
                            e.stopPropagation();
                            buttonState.onClick?.();
                          }}
                        >
                          {buttonState.label}
                        </HoverIconButton>
                      ) : (
                        <Button
                          action={false}
                          tertiary
                          disabled={
                            buttonState.disabled || !buttonState.onClick
                          }
                          onClick={(e) => {
                            e.stopPropagation();
                            buttonState.onClick?.();
                          }}
                          rightIcon={
                            buttonState.icon === "arrow"
                              ? SvgArrowExchange
                              : buttonState.icon === "arrow-circle"
                                ? SvgArrowRightCircle
                                : undefined
                          }
                        >
                          {buttonState.label}
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      <ProviderSetupModal
        isOpen={isModalOpen && !!selectedProviderType}
        onClose={() => {
          setIsModalOpen(false);
          setSelectedProviderType(null);
        }}
        providerLabel={providerLabel}
        providerLogo={renderProviderLogo(
          selectedProviderType
            ? SEARCH_PROVIDER_DETAILS[selectedProviderType]?.logoSrc
            : undefined,
          providerLabel,
          24,
          false,
          28
        )}
        description={
          selectedProviderType
            ? SEARCH_PROVIDER_DETAILS[selectedProviderType]?.helper ??
              SEARCH_PROVIDER_DETAILS[selectedProviderType]?.subtitle ??
              ""
            : ""
        }
        apiKeyValue={apiKeyValue}
        onApiKeyChange={(value) => {
          setApiKeyValue(value);
          // Mark as changed if user is typing something other than the masked placeholder
          if (value !== "••••••••••••••••") {
            setApiKeyChanged(true);
          }
        }}
        optionalField={
          selectedProviderType === "google_pse"
            ? {
                label: "Search Engine ID",
                value: searchEngineIdValue,
                onChange: (value) => setSearchEngineIdValue(value),
                placeholder: "Enter search engine ID",
                description: (
                  <>
                    Paste your{" "}
                    <a
                      href="https://programmablesearchengine.google.com/controlpanel/all"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline"
                    >
                      search engine ID
                    </a>{" "}
                    you want to use for web search.
                  </>
                ),
              }
            : selectedProviderType === "searxng"
              ? {
                  label: "SearXNG Base URL",
                  value: searchEngineIdValue,
                  onChange: (value) => setSearchEngineIdValue(value),
                  placeholder: "https://your-searxng-instance.com",
                  description: (
                    <>
                      Paste the base URL of your{" "}
                      <a
                        href="https://docs.searxng.org/admin/installation.html"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline"
                      >
                        private SearXNG instance
                      </a>
                      .
                    </>
                  ),
                }
              : undefined
        }
        helperMessage={getSearchProviderHelperMessage()}
        helperClass={getSearchProviderHelperClass()}
        isProcessing={isProcessingSearch}
        canConnect={canConnect}
        onConnect={() => {
          void handleSearchConnect();
        }}
        hideApiKey={selectedProviderType === "searxng"}
      />

      <ProviderSetupModal
        isOpen={isContentModalOpen && !!selectedContentProviderType}
        onClose={() => {
          setIsContentModalOpen(false);
          setSelectedContentProviderType(null);
        }}
        providerLabel={contentProviderLabel}
        providerLogo={renderContentProviderLogo(
          selectedContentProviderType || "",
          false,
          24,
          28
        )}
        description={
          selectedContentProviderType
            ? CONTENT_PROVIDER_DETAILS[selectedContentProviderType]
                ?.description ||
              CONTENT_PROVIDER_DETAILS[selectedContentProviderType]?.subtitle ||
              `Provide credentials for ${contentProviderLabel} to enable crawling.`
            : ""
        }
        apiKeyValue={contentApiKeyValue}
        onApiKeyChange={(value) => {
          setContentApiKeyValue(value);
          // Mark as changed if user is typing something other than the masked placeholder
          if (value !== "••••••••••••••••") {
            setContentApiKeyChanged(true);
          }
        }}
        optionalField={
          selectedContentProviderType === "firecrawl"
            ? {
                label: "API Base URL",
                value: contentBaseUrlValue,
                onChange: (value) => setContentBaseUrlValue(value),
                placeholder: "https://",
                description: "Your Firecrawl API base URL.",
                showFirst: true,
              }
            : undefined
        }
        helperMessage={getContentProviderHelperMessage()}
        helperClass={getContentProviderHelperClass()}
        isProcessing={isProcessingContent}
        canConnect={canConnectContent}
        onConnect={() => {
          void handleContentConnect();
        }}
        apiKeyAutoFocus={
          !selectedContentProviderType ||
          selectedContentProviderType !== "firecrawl"
        }
      />
    </>
  );
}
