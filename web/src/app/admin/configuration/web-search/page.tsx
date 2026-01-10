"use client";

import Image from "next/image";
import { useMemo, useState, useReducer } from "react";
import { AdminPageTitle } from "@/components/admin/Title";
import { InfoIcon } from "@/components/icons/icons";
import Text from "@/refresh-components/texts/Text";
import Separator from "@/refresh-components/Separator";
import useSWR from "swr";
import { errorHandlingFetcher, FetchError } from "@/lib/fetcher";
import { ThreeDotsLoader } from "@/components/Loading";
import { Callout } from "@/components/ui/callout";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn } from "@/lib/utils";
import {
  SvgArrowExchange,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgEdit,
  SvgGlobe,
  SvgOnyxLogo,
  SvgX,
} from "@opal/icons";

import { WebProviderSetupModal } from "@/app/admin/configuration/web-search/WebProviderSetupModal";
import {
  SEARCH_PROVIDERS_URL,
  SEARCH_PROVIDER_DETAILS,
  SEARCH_PROVIDER_ORDER,
  getSearchProviderDisplayLabel,
  buildSearchProviderConfig,
  canConnectSearchProvider,
  getSingleConfigFieldValueForForm,
  isBuiltInSearchProviderType,
  isSearchProviderConfigured,
  searchProviderRequiresApiKey,
  type WebSearchProviderType,
} from "@/app/admin/configuration/web-search/searchProviderUtils";
import {
  CONTENT_PROVIDERS_URL,
  CONTENT_PROVIDER_DETAILS,
  CONTENT_PROVIDER_ORDER,
  buildContentProviderConfig,
  canConnectContentProvider,
  getSingleContentConfigFieldValueForForm,
  getCurrentContentProviderType,
  isContentProviderConfigured,
  type WebContentProviderType,
} from "@/app/admin/configuration/web-search/contentProviderUtils";
import {
  initialWebProviderModalState,
  WebProviderModalReducer,
  MASKED_API_KEY_PLACEHOLDER,
} from "@/app/admin/configuration/web-search/WebProviderModalReducer";
import { connectProviderFlow } from "@/app/admin/configuration/web-search/connectProviderFlow";

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

interface HoverIconButtonProps extends React.ComponentProps<typeof Button> {
  isHovered: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  children: React.ReactNode;
}

function HoverIconButton({
  isHovered,
  onMouseEnter,
  onMouseLeave,
  children,
  ...buttonProps
}: HoverIconButtonProps) {
  return (
    <div onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}>
      <Button {...buttonProps} rightIcon={isHovered ? SvgX : SvgCheckSquare}>
        {children}
      </Button>
    </div>
  );
}

export default function Page() {
  const [searchModal, dispatchSearchModal] = useReducer(
    WebProviderModalReducer,
    initialWebProviderModalState
  );
  const [contentModal, dispatchContentModal] = useReducer(
    WebProviderModalReducer,
    initialWebProviderModalState
  );
  const [activationError, setActivationError] = useState<string | null>(null);
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

  // Modal form state is owned by reducers

  const openSearchModal = (
    providerType: WebSearchProviderType,
    provider?: WebSearchProviderView
  ) => {
    const requiresApiKey = searchProviderRequiresApiKey(providerType);
    const hasStoredKey = provider?.has_api_key ?? false;

    dispatchSearchModal({
      type: "OPEN",
      providerType,
      existingProviderId: provider?.id ?? null,
      initialApiKeyValue:
        requiresApiKey && hasStoredKey ? MASKED_API_KEY_PLACEHOLDER : "",
      initialConfigValue: getSingleConfigFieldValueForForm(
        providerType,
        provider
      ),
    });
  };

  const openContentModal = (
    providerType: WebContentProviderType,
    provider?: WebContentProviderView
  ) => {
    const hasStoredKey = provider?.has_api_key ?? false;
    const defaultFirecrawlBaseUrl = "https://api.firecrawl.dev/v1/scrape";

    dispatchContentModal({
      type: "OPEN",
      providerType,
      existingProviderId: provider?.id ?? null,
      initialApiKeyValue: hasStoredKey ? MASKED_API_KEY_PLACEHOLDER : "",
      initialConfigValue:
        providerType === "firecrawl"
          ? getSingleContentConfigFieldValueForForm(
              providerType,
              provider,
              defaultFirecrawlBaseUrl
            )
          : "",
    });
  };

  const hasActiveSearchProvider = searchProviders.some(
    (provider) => provider.is_active
  );

  const hasConfiguredSearchProvider = searchProviders.some((provider) =>
    isSearchProviderConfigured(provider.provider_type, provider)
  );

  const combinedSearchProviders = useMemo(() => {
    const byType = new Map(
      searchProviders.map((p) => [p.provider_type, p] as const)
    );

    const ordered = SEARCH_PROVIDER_ORDER.map((providerType) => {
      const provider = byType.get(providerType);
      const details = SEARCH_PROVIDER_DETAILS[providerType];
      return {
        key: provider?.id ?? providerType,
        providerType,
        label: getSearchProviderDisplayLabel(providerType, provider?.name),
        subtitle: details.subtitle,
        logoSrc: details.logoSrc,
        provider,
      };
    });

    const additional = searchProviders
      .filter((p) => !SEARCH_PROVIDER_ORDER.includes(p.provider_type))
      .map((provider) => ({
        key: provider.id,
        providerType: provider.provider_type,
        label: getSearchProviderDisplayLabel(
          provider.provider_type,
          provider.name
        ),
        subtitle: "Custom integration",
        logoSrc: undefined,
        provider,
      }));

    return [...ordered, ...additional];
  }, [searchProviders]);

  const selectedProviderType =
    searchModal.providerType as WebSearchProviderType | null;
  const selectedContentProviderType =
    contentModal.providerType as WebContentProviderType | null;

  const providerLabel = selectedProviderType
    ? getSearchProviderDisplayLabel(selectedProviderType)
    : "";
  const searchProviderValues = useMemo(
    () => ({
      apiKey: searchModal.apiKeyValue.trim(),
      config: searchModal.configValue.trim(),
    }),
    [searchModal.apiKeyValue, searchModal.configValue]
  );
  const canConnect =
    !!selectedProviderType &&
    canConnectSearchProvider(
      selectedProviderType,
      searchProviderValues.apiKey,
      searchProviderValues.config
    );
  const contentProviderLabel = selectedContentProviderType
    ? CONTENT_PROVIDER_DETAILS[selectedContentProviderType]?.label ||
      selectedContentProviderType
    : "";
  const contentProviderValues = useMemo(
    () => ({
      apiKey: contentModal.apiKeyValue.trim(),
      config: contentModal.configValue.trim(),
    }),
    [contentModal.apiKeyValue, contentModal.configValue]
  );
  const canConnectContent =
    !!selectedContentProviderType &&
    canConnectContentProvider(
      selectedContentProviderType,
      contentProviderValues.apiKey,
      contentProviderValues.config
    );

  const renderLogo = ({
    logoSrc,
    alt,
    fallback,
    size = 16,
    isHighlighted = false,
    containerSize,
  }: {
    logoSrc?: string;
    alt: string;
    fallback?: React.ReactNode;
    size?: number;
    isHighlighted?: boolean;
    containerSize?: number;
  }) => {
    const containerSizeClass =
      size === 24 || containerSize === 28 ? "size-7" : "size-5";

    return (
      <div
        className={cn(
          "flex items-center justify-center px-0.5 py-0 shrink-0 overflow-clip",
          containerSizeClass
        )}
      >
        {logoSrc ? (
          <Image src={logoSrc} alt={alt} width={size} height={size} />
        ) : fallback ? (
          fallback
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

  const combinedContentProviders = useMemo(() => {
    const byType = new Map(
      contentProviders.map((p) => [p.provider_type, p] as const)
    );

    // Always include our built-in providers in a stable order. If missing, inject
    // a virtual placeholder so the UI can still render/activate it.
    const ordered = CONTENT_PROVIDER_ORDER.map((providerType) => {
      const existing = byType.get(providerType);
      if (existing) return existing;

      if (providerType === "onyx_web_crawler") {
        return {
          id: -1,
          name: "Onyx Web Crawler",
          provider_type: "onyx_web_crawler",
          is_active: true,
          config: null,
          has_api_key: true,
        } satisfies WebContentProviderView;
      }

      if (providerType === "firecrawl") {
        return {
          id: -2,
          name: "Firecrawl",
          provider_type: "firecrawl",
          is_active: false,
          config: null,
          has_api_key: false,
        } satisfies WebContentProviderView;
      }

      return null;
    }).filter(Boolean) as WebContentProviderView[];

    const additional = contentProviders.filter(
      (p) => !CONTENT_PROVIDER_ORDER.includes(p.provider_type)
    );

    return [...ordered, ...additional];
  }, [contentProviders]);

  const currentContentProviderType =
    getCurrentContentProviderType(contentProviders);

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
      <>
        <AdminPageTitle
          title="Web Search"
          icon={SvgGlobe}
          includeDivider={false}
        />
        <Callout type="danger" title="Failed to load web search settings">
          {message}
          {detail && (
            <Text as="p" className="mt-2 text-text-03" mainContentBody text03>
              {detail}
            </Text>
          )}
        </Callout>
      </>
    );
  }

  if (isLoading) {
    return (
      <>
        <AdminPageTitle
          title="Web Search"
          icon={SvgGlobe}
          includeDivider={false}
        />
        <div className="mt-8">
          <ThreeDotsLoader />
        </div>
      </>
    );
  }

  const handleSearchConnect = async () => {
    if (!selectedProviderType) {
      return;
    }

    const config = buildSearchProviderConfig(
      selectedProviderType,
      searchProviderValues.config
    );

    // Use the stored provider ID from the modal state instead of looking it up again.
    // This ensures we update the correct provider even if the data has changed.
    const existingProviderId = searchModal.existingProviderId;
    const existingProvider = existingProviderId
      ? searchProviders.find((p) => p.id === existingProviderId)
      : null;

    const providerRequiresApiKey =
      searchProviderRequiresApiKey(selectedProviderType);
    // Only consider "API key changed" for providers that actually use API keys,
    // and only when a real key (not the masked placeholder) is provided.
    const apiKeyChangedForProvider =
      providerRequiresApiKey &&
      searchModal.apiKeyValue !== MASKED_API_KEY_PLACEHOLDER &&
      searchProviderValues.apiKey.length > 0;

    // Check if config changed from stored values
    const storedConfigValue = getSingleConfigFieldValueForForm(
      selectedProviderType,
      existingProvider
    );
    const configChanged =
      Object.keys(config).length > 0 &&
      storedConfigValue !== searchProviderValues.config;

    dispatchSearchModal({ type: "SET_PHASE", phase: "saving" });
    dispatchSearchModal({ type: "CLEAR_MESSAGE" });
    setActivationError(null);

    await connectProviderFlow({
      category: "search",
      providerType: selectedProviderType,
      existingProviderId: existingProvider?.id ?? null,
      existingProviderName: existingProvider?.name ?? null,
      existingProviderHasApiKey: existingProvider?.has_api_key ?? false,
      displayName:
        SEARCH_PROVIDER_DETAILS[selectedProviderType]?.label ??
        selectedProviderType,
      providerRequiresApiKey,
      apiKeyChangedForProvider,
      apiKey: searchProviderValues.apiKey,
      config,
      configChanged,
      onValidating: (message) => (
        dispatchSearchModal({ type: "SET_PHASE", phase: "validating" }),
        dispatchSearchModal({ type: "SET_STATUS_MESSAGE", text: message })
      ),
      onSaving: (message) => (
        dispatchSearchModal({ type: "SET_PHASE", phase: "saving" }),
        dispatchSearchModal({ type: "SET_STATUS_MESSAGE", text: message })
      ),
      onError: (message) =>
        dispatchSearchModal({ type: "SET_ERROR_MESSAGE", text: message }),
      onClose: () => {
        dispatchSearchModal({ type: "CLOSE" });
      },
      mutate: mutateSearchProviders,
    });
  };

  const handleActivateSearchProvider = async (providerId: number) => {
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
    }
  };

  const handleDeactivateSearchProvider = async (providerId: number) => {
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
    }
  };

  const handleActivateContentProvider = async (
    provider: WebContentProviderView
  ) => {
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
            CONTENT_PROVIDER_DETAILS[provider.provider_type]?.label ||
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
    }
  };

  const handleDeactivateContentProvider = async (
    providerId: number,
    providerType: string
  ) => {
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
    }
  };

  const getContentProviderHelperMessage = () => {
    if (contentModal.message?.kind === "error") {
      return contentModal.message.text;
    }
    if (contentModal.message?.kind === "status") {
      return contentModal.message.text;
    }
    if (
      contentModal.phase === "validating" ||
      contentModal.phase === "saving"
    ) {
      return "Validating API key...";
    }

    const providerName = selectedContentProviderType
      ? CONTENT_PROVIDER_DETAILS[selectedContentProviderType]?.label ||
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
    if (contentModal.message?.kind === "error") return "text-status-error-05";
    if (contentModal.message?.kind === "status") {
      return contentModal.message.text.toLowerCase().includes("validated")
        ? "text-green-500"
        : "text-text-03";
    }
    return "text-text-03";
  };

  const handleContentConnect = async () => {
    if (!selectedContentProviderType) {
      return;
    }

    const config = buildContentProviderConfig(
      selectedContentProviderType,
      contentProviderValues.config
    );

    // Use the stored provider ID from the modal state instead of looking it up again.
    // This ensures we update the correct provider even if the data has changed.
    const existingProviderId = contentModal.existingProviderId;
    const existingProvider = existingProviderId
      ? contentProviders.find((p) => p.id === existingProviderId)
      : null;

    // Check if config changed from stored values
    const storedBaseUrl = getSingleContentConfigFieldValueForForm(
      selectedContentProviderType,
      existingProvider,
      "https://api.firecrawl.dev/v1/scrape"
    );
    const configChanged =
      selectedContentProviderType === "firecrawl" &&
      storedBaseUrl !== contentProviderValues.config;

    // Reuse shared connect flow for key-based providers (firecrawl + similar).
    // Note: onyx_web_crawler doesn't go through this modal.
    dispatchContentModal({ type: "SET_PHASE", phase: "saving" });
    dispatchContentModal({ type: "CLEAR_MESSAGE" });

    await connectProviderFlow({
      category: "content",
      providerType: selectedContentProviderType,
      existingProviderId: existingProvider?.id ?? null,
      existingProviderName: existingProvider?.name ?? null,
      existingProviderHasApiKey: existingProvider?.has_api_key ?? false,
      displayName:
        CONTENT_PROVIDER_DETAILS[selectedContentProviderType]?.label ??
        selectedContentProviderType,
      providerRequiresApiKey: true,
      apiKeyChangedForProvider:
        contentModal.apiKeyValue !== MASKED_API_KEY_PLACEHOLDER &&
        contentProviderValues.apiKey.length > 0,
      apiKey: contentProviderValues.apiKey,
      config,
      configChanged,
      onValidating: (message) => (
        dispatchContentModal({ type: "SET_PHASE", phase: "validating" }),
        dispatchContentModal({ type: "SET_STATUS_MESSAGE", text: message })
      ),
      onSaving: (message) => (
        dispatchContentModal({ type: "SET_PHASE", phase: "saving" }),
        dispatchContentModal({ type: "SET_STATUS_MESSAGE", text: message })
      ),
      onError: (message) =>
        dispatchContentModal({ type: "SET_ERROR_MESSAGE", text: message }),
      onClose: () => {
        dispatchContentModal({ type: "CLOSE" });
      },
      mutate: mutateContentProviders,
    });
  };

  return (
    <>
      <>
        <AdminPageTitle icon={SvgGlobe} title="Web Search" />
        <div className="pt-4 pb-4">
          <Text as="p" className="text-text-dark">
            Search settings for external search across the internet.
          </Text>
        </div>

        <Separator />

        <div className="flex w-full flex-col gap-8 pb-6">
          <div className="flex w-full max-w-[960px] flex-col gap-3">
            <div className="flex flex-col gap-0.5">
              <Text as="p" mainContentEmphasis text05>
                Search Engine
              </Text>
              <Text
                as="p"
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
                  <Text as="p" className="flex-1 px-0.5" mainUiBody text04>
                    {hasConfiguredSearchProvider
                      ? "Select a search engine to enable web search."
                      : "Connect a search engine to set up web search."}
                  </Text>
                </div>
              </div>
            )}

            <div className="flex flex-col gap-2">
              {combinedSearchProviders.map(
                ({ key, providerType, label, subtitle, logoSrc, provider }) => {
                  const isConfigured = isSearchProviderConfigured(
                    providerType,
                    provider
                  );
                  const isActive = provider?.is_active ?? false;
                  const isHighlighted = isActive;
                  const providerId = provider?.id;
                  const canOpenModal =
                    isBuiltInSearchProviderType(providerType);

                  const buttonState = (() => {
                    if (!provider || !isConfigured) {
                      return {
                        label: "Connect",
                        disabled: false,
                        icon: "arrow" as const,
                        onClick: canOpenModal
                          ? () => {
                              openSearchModal(providerType, provider);
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
                      label: "Set as Default",
                      disabled: false,
                      icon: "arrow-circle" as const,
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
                      className={cn(
                        "flex items-start justify-between gap-3 rounded-16 border p-1 bg-background-neutral-00",
                        isHighlighted
                          ? "border-action-link-05"
                          : "border-border-01",
                        isCardClickable &&
                          "cursor-pointer hover:bg-background-tint-01 transition-colors"
                      )}
                    >
                      <div className="flex flex-1 items-start gap-1 px-2 py-1">
                        {renderLogo({
                          logoSrc,
                          alt: `${label} logo`,
                          size: 16,
                          isHighlighted,
                        })}
                        <div className="flex flex-col gap-0.5">
                          <Text as="p" mainUiAction text05>
                            {label}
                          </Text>
                          <Text as="p" secondaryBody text03>
                            {subtitle}
                          </Text>
                        </div>
                      </div>
                      <div className="flex items-center justify-end gap-2">
                        {isConfigured && (
                          <IconButton
                            icon={SvgEdit}
                            tooltip="Edit"
                            internal
                            tertiary
                            onClick={() => {
                              if (!canOpenModal) return;
                              openSearchModal(
                                providerType as WebSearchProviderType,
                                provider
                              );
                            }}
                            aria-label={`Edit ${label}`}
                          />
                        )}
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

          <div className="flex w-full max-w-[960px] flex-col gap-3">
            <div className="flex flex-col gap-0.5">
              <Text as="p" mainContentEmphasis text05>
                Web Crawler
              </Text>
              <Text
                as="p"
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

            <div className="flex flex-col gap-2">
              {combinedContentProviders.map((provider) => {
                const label =
                  provider.name ||
                  CONTENT_PROVIDER_DETAILS[provider.provider_type]?.label ||
                  provider.provider_type;

                const subtitle =
                  CONTENT_PROVIDER_DETAILS[provider.provider_type]?.subtitle ||
                  provider.provider_type;

                const providerId = provider.id;
                const isConfigured = isContentProviderConfigured(
                  provider.provider_type,
                  provider
                );
                const isCurrentCrawler =
                  provider.provider_type === currentContentProviderType;

                const buttonState = (() => {
                  if (!isConfigured) {
                    return {
                      label: "Connect",
                      icon: "arrow" as const,
                      disabled: false,
                      onClick: () => {
                        openContentModal(provider.provider_type, provider);
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
                    label: "Set as Default",
                    icon: "arrow-circle" as const,
                    disabled: !canActivate,
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
                    className={cn(
                      "flex items-start justify-between gap-3 rounded-16 border p-1 bg-background-neutral-00",
                      isCurrentCrawler
                        ? "border-action-link-05"
                        : "border-border-01",
                      isContentCardClickable &&
                        "cursor-pointer hover:bg-background-tint-01 transition-colors"
                    )}
                  >
                    <div className="flex flex-1 items-start gap-1 px-2 py-1">
                      {renderLogo({
                        logoSrc:
                          CONTENT_PROVIDER_DETAILS[provider.provider_type]
                            ?.logoSrc,
                        alt: `${label} logo`,
                        fallback:
                          provider.provider_type === "onyx_web_crawler" ? (
                            <SvgOnyxLogo width={16} height={16} />
                          ) : undefined,
                        size: 16,
                        isHighlighted: isCurrentCrawler,
                      })}
                      <div className="flex flex-col gap-0.5">
                        <Text as="p" mainUiAction text05>
                          {label}
                        </Text>
                        <Text as="p" secondaryBody text03>
                          {subtitle}
                        </Text>
                      </div>
                    </div>
                    <div className="flex items-center justify-end gap-2">
                      {provider.provider_type !== "onyx_web_crawler" &&
                        isConfigured && (
                          <IconButton
                            icon={SvgEdit}
                            tooltip="Edit"
                            internal
                            tertiary
                            onClick={() => {
                              openContentModal(
                                provider.provider_type,
                                provider
                              );
                            }}
                            aria-label={`Edit ${label}`}
                          />
                        )}
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
      </>

      <WebProviderSetupModal
        isOpen={selectedProviderType !== null}
        onClose={() => {
          dispatchSearchModal({ type: "CLOSE" });
        }}
        providerLabel={providerLabel}
        providerLogo={renderLogo({
          logoSrc: selectedProviderType
            ? SEARCH_PROVIDER_DETAILS[selectedProviderType]?.logoSrc
            : undefined,
          alt: `${providerLabel} logo`,
          size: 24,
          containerSize: 28,
        })}
        description={
          selectedProviderType
            ? SEARCH_PROVIDER_DETAILS[selectedProviderType]?.helper ??
              SEARCH_PROVIDER_DETAILS[selectedProviderType]?.subtitle ??
              ""
            : ""
        }
        apiKeyValue={searchModal.apiKeyValue}
        onApiKeyChange={(value) =>
          dispatchSearchModal({ type: "SET_API_KEY", value })
        }
        optionalField={
          selectedProviderType === "google_pse"
            ? {
                label: "Search Engine ID",
                value: searchModal.configValue,
                onChange: (value) =>
                  dispatchSearchModal({ type: "SET_CONFIG_VALUE", value }),
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
                  value: searchModal.configValue,
                  onChange: (value) =>
                    dispatchSearchModal({ type: "SET_CONFIG_VALUE", value }),
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
        helperMessage={
          searchModal.message?.kind === "error" ? (
            searchModal.message.text
          ) : searchModal.phase === "validating" ||
            searchModal.phase === "saving" ? (
            "Checking connection..."
          ) : (
            <>
              Paste your{" "}
              <a
                href={
                  (selectedProviderType
                    ? SEARCH_PROVIDER_DETAILS[selectedProviderType]?.apiKeyUrl
                    : undefined) ?? "#"
                }
                target="_blank"
                rel="noopener noreferrer"
                className="underline"
              >
                API key
              </a>{" "}
              to access your search engine.
            </>
          )
        }
        helperClass={
          searchModal.message?.kind === "error"
            ? "text-status-error-05"
            : searchModal.phase === "validating" ||
                searchModal.phase === "saving"
              ? "text-text-03"
              : "text-text-03"
        }
        isProcessing={
          searchModal.phase === "validating" || searchModal.phase === "saving"
        }
        canConnect={canConnect}
        onConnect={() => {
          void handleSearchConnect();
        }}
        hideApiKey={
          !!selectedProviderType &&
          !searchProviderRequiresApiKey(selectedProviderType)
        }
      />

      <WebProviderSetupModal
        isOpen={selectedContentProviderType !== null}
        onClose={() => {
          dispatchContentModal({ type: "CLOSE" });
        }}
        providerLabel={contentProviderLabel}
        providerLogo={renderLogo({
          logoSrc: selectedContentProviderType
            ? CONTENT_PROVIDER_DETAILS[selectedContentProviderType]?.logoSrc
            : undefined,
          alt: `${
            contentProviderLabel || selectedContentProviderType || "provider"
          } logo`,
          fallback:
            selectedContentProviderType === "onyx_web_crawler" ? (
              <SvgOnyxLogo width={24} height={24} className="text-text-05" />
            ) : undefined,
          size: 24,
          containerSize: 28,
        })}
        description={
          selectedContentProviderType
            ? CONTENT_PROVIDER_DETAILS[selectedContentProviderType]
                ?.description ||
              CONTENT_PROVIDER_DETAILS[selectedContentProviderType]?.subtitle ||
              `Provide credentials for ${contentProviderLabel} to enable crawling.`
            : ""
        }
        apiKeyValue={contentModal.apiKeyValue}
        onApiKeyChange={(value) =>
          dispatchContentModal({ type: "SET_API_KEY", value })
        }
        optionalField={
          selectedContentProviderType === "firecrawl"
            ? {
                label: "API Base URL",
                value: contentModal.configValue,
                onChange: (value) =>
                  dispatchContentModal({ type: "SET_CONFIG_VALUE", value }),
                placeholder: "https://",
                description: "Your Firecrawl API base URL.",
                showFirst: true,
              }
            : undefined
        }
        helperMessage={getContentProviderHelperMessage()}
        helperClass={getContentProviderHelperClass()}
        isProcessing={
          contentModal.phase === "validating" || contentModal.phase === "saving"
        }
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
