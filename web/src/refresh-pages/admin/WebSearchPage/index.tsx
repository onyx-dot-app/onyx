"use client";

import Image from "next/image";
import { useEffect, useMemo, useState, useReducer } from "react";
import { useTranslations } from "next-intl";
import { InfoIcon } from "@/components/icons/icons";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Content, Card } from "@opal/layouts";
import { markdown } from "@opal/utils";
import useSWR from "swr";
import { errorHandlingFetcher, FetchError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ThreeDotsLoader } from "@/components/Loading";
import { Callout } from "@/components/ui/callout";
import { cn } from "@/lib/utils";
import { toast } from "@/hooks/useToast";
import {
  SvgArrowExchange,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgGlobe,
  SvgSettings,
  SvgSlash,
  SvgUnplug,
} from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import { Button, SelectCard } from "@opal/components";
import { Hoverable } from "@opal/core";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { WebProviderSetupModal } from "@/refresh-pages/admin/WebSearchPage/WebProviderSetupModal";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import {
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
} from "@/refresh-pages/admin/WebSearchPage/searchProviderUtils";
import {
  CONTENT_PROVIDER_DETAILS,
  CONTENT_PROVIDER_ORDER,
  buildContentProviderConfig,
  canConnectContentProvider,
  getSingleContentConfigFieldValueForForm,
  getCurrentContentProviderType,
  isContentProviderConfigured,
  type WebContentProviderType,
} from "@/refresh-pages/admin/WebSearchPage/contentProviderUtils";
import {
  initialWebProviderModalState,
  WebProviderModalReducer,
  MASKED_API_KEY_PLACEHOLDER,
} from "@/refresh-pages/admin/WebSearchPage/WebProviderModalReducer";
import { connectProviderFlow } from "@/refresh-pages/admin/WebSearchPage/connectProviderFlow";
import {
  activateSearchProvider,
  deactivateSearchProvider,
  activateContentProvider,
  deactivateContentProvider,
  disconnectProvider,
} from "@/refresh-pages/admin/WebSearchPage/svc";
import type {
  WebSearchProviderView,
  WebContentProviderView,
  DisconnectTargetState,
} from "@/refresh-pages/admin/WebSearchPage/interfaces";

const NO_DEFAULT_VALUE = "__none__";

const route = ADMIN_ROUTES.WEB_SEARCH;

// ---------------------------------------------------------------------------
// WebSearchDisconnectModal
// ---------------------------------------------------------------------------

function WebSearchDisconnectModal({
  disconnectTarget,
  searchProviders,
  contentProviders,
  replacementProviderId,
  onReplacementChange,
  onClose,
  onDisconnect,
}: {
  disconnectTarget: DisconnectTargetState;
  searchProviders: WebSearchProviderView[];
  contentProviders: WebContentProviderView[];
  replacementProviderId: string | null;
  onReplacementChange: (id: string | null) => void;
  onClose: () => void;
  onDisconnect: () => void;
}) {
  const t = useTranslations("admin.webSearch");
  const isSearch = disconnectTarget.category === "search";

  // Determine if the target is currently the active/selected provider
  const isActive = isSearch
    ? searchProviders.find((p) => p.id === disconnectTarget.id)?.is_active ??
      false
    : contentProviders.find((p) => p.id === disconnectTarget.id)?.is_active ??
      false;

  // Find other configured providers as replacements
  const replacementOptions = isSearch
    ? searchProviders.filter(
        (p) => p.id !== disconnectTarget.id && p.id > 0 && p.has_api_key
      )
    : contentProviders.filter(
        (p) =>
          p.id !== disconnectTarget.id &&
          p.provider_type !== "onyx_web_crawler" &&
          p.id > 0 &&
          p.has_api_key
      );

  const needsReplacement = isActive;
  const hasReplacements = replacementOptions.length > 0;

  const getLabel = (p: { name: string; provider_type: string }) => {
    if (isSearch) {
      const details =
        SEARCH_PROVIDER_DETAILS[p.provider_type as WebSearchProviderType];
      return details?.label ?? p.name ?? p.provider_type;
    }
    const details = CONTENT_PROVIDER_DETAILS[p.provider_type];
    return details?.label ?? p.name ?? p.provider_type;
  };

  const categoryLabel = isSearch ? t("searchEngineLabel") : t("webCrawlerLabel");
  const featureLabel = isSearch ? t("webSearchLabel") : t("webCrawlingLabel");
  const disableLabel = isSearch ? t("disableWebSearch") : t("disableWebCrawling");

  // Auto-select first replacement when modal opens
  useEffect(() => {
    if (needsReplacement && hasReplacements && !replacementProviderId) {
      const first = replacementOptions[0];
      if (first) onReplacementChange(String(first.id));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ConfirmationModalLayout
      icon={SvgUnplug}
      title={markdown(`Disconnect *${disconnectTarget.label}*`)}
      description={t("disconnectModalDescription")}
      onClose={onClose}
      submit={
        <Button
          variant="danger"
          onClick={onDisconnect}
          disabled={
            needsReplacement && hasReplacements && !replacementProviderId
          }
        >
          {t("disconnect")}
        </Button>
      }
    >
      {needsReplacement ? (
        hasReplacements ? (
          <Section alignItems="start">
            <Text as="p" text03>
              <b>{disconnectTarget.label}</b> {isSearch ? t("searchEngineActive") : t("webCrawlerActive")} {categoryLabel}. {t("searchHistoryPreserved")}
            </Text>
            <Section alignItems="start" gap={0.25}>
              <Text as="p" secondaryBody text03>
                {t("setNewDefault")}
              </Text>
              <InputSelect
                value={replacementProviderId ?? undefined}
                onValueChange={(v) => onReplacementChange(v)}
              >
                <InputSelect.Trigger placeholder={t("selectReplacement")} />
                <InputSelect.Content>
                  {replacementOptions.map((p) => (
                    <InputSelect.Item key={p.id} value={String(p.id)}>
                      {getLabel(p)}
                    </InputSelect.Item>
                  ))}
                  <InputSelect.Separator />
                  <InputSelect.Item value={NO_DEFAULT_VALUE} icon={SvgSlash}>
                    <span>
                      <b>{t("noDefault")}</b>
                      <span className="text-text-03"> ({disableLabel})</span>
                    </span>
                  </InputSelect.Item>
                </InputSelect.Content>
              </InputSelect>
            </Section>
          </Section>
        ) : (
          <>
            <Text as="p" text03>
              <b>{disconnectTarget.label}</b> {isSearch ? t("searchEngineActive") : t("webCrawlerActive")} {categoryLabel}.
            </Text>
            <Text as="p" text03>
              {t("connectAnotherProvider", { feature: featureLabel })}
            </Text>
          </>
        )
      ) : (
        <>
          <Text as="p" text03>
            {isSearch ? t("webSearchLabel") : t("webCrawlingLabel")} {t("noLongerRouted", { label: disconnectTarget.label })}
          </Text>
          <Text as="p" text03>
            {t("searchHistoryPreserved")}
          </Text>
        </>
      )}
    </ConfirmationModalLayout>
  );
}

// ---------------------------------------------------------------------------
// ProviderCard — uses SelectCard for stateful interactive provider cards
// ---------------------------------------------------------------------------

type ProviderStatus = "disconnected" | "connected" | "selected";

interface ProviderCardProps {
  icon: React.FunctionComponent<{ size?: number; className?: string }>;
  title: string;
  description: string;
  status: ProviderStatus;
  onConnect?: () => void;
  onSelect?: () => void;
  onDeselect?: () => void;
  onEdit?: () => void;
  onDisconnect?: () => void;
  selectedLabel?: string;
}

const STATUS_TO_STATE = {
  disconnected: "empty",
  connected: "filled",
  selected: "selected",
} as const;

function ProviderCard({
  icon,
  title,
  description,
  status,
  onConnect,
  onSelect,
  onDeselect,
  onEdit,
  onDisconnect,
  selectedLabel,
}: ProviderCardProps) {
  const t = useTranslations("admin.webSearch");
  const resolvedSelectedLabel = selectedLabel ?? t("currentDefault");
  const isDisconnected = status === "disconnected";
  const isConnected = status === "connected";
  const isSelected = status === "selected";

  return (
    <Hoverable.Root group="web-search/ProviderCard">
      <SelectCard
        state={STATUS_TO_STATE[status]}
        padding="sm"
        rounding="lg"
        onClick={
          isDisconnected && onConnect
            ? onConnect
            : isSelected && onDeselect
              ? onDeselect
              : undefined
        }
      >
        <Card.Header
          sizePreset="main-ui"
          variant="section"
          icon={icon}
          title={title}
          description={description}
          rightChildren={
            isDisconnected && onConnect ? (
              <Button
                prominence="tertiary"
                rightIcon={SvgArrowExchange}
                onClick={(e) => {
                  e.stopPropagation();
                  onConnect();
                }}
              >
                {t("connect")}
              </Button>
            ) : isConnected && onSelect ? (
              <Button
                prominence="tertiary"
                rightIcon={SvgArrowRightCircle}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect();
                }}
              >
                {t("setAsDefault")}
              </Button>
            ) : isSelected ? (
              <div className="p-2">
                <Content
                  title={resolvedSelectedLabel}
                  sizePreset="main-ui"
                  variant="section"
                  icon={SvgCheckSquare}
                />
              </div>
            ) : undefined
          }
          bottomRightChildren={
            !isDisconnected ? (
              <div className="flex flex-row px-1 pb-1">
                {onDisconnect && (
                  <Hoverable.Item group="web-search/ProviderCard">
                    <Button
                      icon={SvgUnplug}
                      tooltip={t("disconnect")}
                      aria-label={`Disconnect ${title}`}
                      prominence="tertiary"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDisconnect();
                      }}
                      size="md"
                    />
                  </Hoverable.Item>
                )}
                {onEdit && (
                  <Button
                    icon={SvgSettings}
                    tooltip={t("edit")}
                    aria-label={t("edit") + " " + title}
                    prominence="tertiary"
                    onClick={(e) => {
                      e.stopPropagation();
                      onEdit();
                    }}
                    size="md"
                  />
                )}
              </div>
            ) : undefined
          }
        />
      </SelectCard>
    </Hoverable.Root>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function WebSearchPage() {
  const t = useTranslations("admin.webSearch");
  const [searchModal, dispatchSearchModal] = useReducer(
    WebProviderModalReducer,
    initialWebProviderModalState
  );
  const [disconnectTarget, setDisconnectTarget] =
    useState<DisconnectTargetState | null>(null);
  const [replacementProviderId, setReplacementProviderId] = useState<
    string | null
  >(null);
  const [contentModal, dispatchContentModal] = useReducer(
    WebProviderModalReducer,
    initialWebProviderModalState
  );
  const [activationError, setActivationError] = useState<string | null>(null);
  const [contentActivationError, setContentActivationError] = useState<
    string | null
  >(null);
  const {
    data: searchProvidersData,
    error: searchProvidersError,
    isLoading: isLoadingSearchProviders,
    mutate: mutateSearchProviders,
  } = useSWR<WebSearchProviderView[]>(
    SWR_KEYS.webSearchSearchProviders,
    errorHandlingFetcher
  );

  const {
    data: contentProvidersData,
    error: contentProvidersError,
    isLoading: isLoadingContentProviders,
    mutate: mutateContentProviders,
  } = useSWR<WebContentProviderView[]>(
    SWR_KEYS.webSearchContentProviders,
    errorHandlingFetcher
  );

  const searchProviders = searchProvidersData ?? [];
  const contentProviders = contentProvidersData ?? [];

  const isLoading = isLoadingSearchProviders || isLoadingContentProviders;

  // Exa shares API key between search and content providers
  const exaSearchProvider = searchProviders.find(
    (p) => p.provider_type === "exa"
  );
  const exaContentProvider = contentProviders.find(
    (p) => p.provider_type === "exa"
  );
  const hasSharedExaKey =
    (exaSearchProvider?.has_api_key || exaContentProvider?.has_api_key) ??
    false;

  // Modal form state is owned by reducers

  const openSearchModal = (
    providerType: WebSearchProviderType,
    provider?: WebSearchProviderView
  ) => {
    const requiresApiKey = searchProviderRequiresApiKey(providerType);
    const hasStoredKey = provider?.has_api_key ?? false;

    // For Exa search provider, check if we can use the shared Exa key
    const isExa = providerType === "exa";
    const canUseSharedExaKey = isExa && hasSharedExaKey && !hasStoredKey;

    dispatchSearchModal({
      type: "OPEN",
      providerType,
      existingProviderId: provider?.id ?? null,
      initialApiKeyValue:
        requiresApiKey && (hasStoredKey || canUseSharedExaKey)
          ? MASKED_API_KEY_PLACEHOLDER
          : "",
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
    const defaultFirecrawlBaseUrl = "https://api.firecrawl.dev/v2/scrape";

    // For Exa content provider, check if we can use the shared Exa key
    const isExa = providerType === "exa";
    const canUseSharedExaKey = isExa && hasSharedExaKey && !hasStoredKey;

    dispatchContentModal({
      type: "OPEN",
      providerType,
      existingProviderId: provider?.id ?? null,
      initialApiKeyValue:
        hasStoredKey || canUseSharedExaKey ? MASKED_API_KEY_PLACEHOLDER : "",
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
        subtitle: t("customIntegration"),
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
    containerSize,
  }: {
    logoSrc?: string;
    alt: string;
    fallback?: React.ReactNode;
    size?: number;
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
          <SvgGlobe size={size} className="text-text-02" />
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

      if (providerType === "exa") {
        return {
          id: -3,
          name: "Exa",
          provider_type: "exa",
          is_active: false,
          config: null,
          has_api_key: hasSharedExaKey,
        } satisfies WebContentProviderView;
      }

      return null;
    }).filter(Boolean) as WebContentProviderView[];

    const additional = contentProviders.filter(
      (p) => !CONTENT_PROVIDER_ORDER.includes(p.provider_type)
    );

    return [...ordered, ...additional];
  }, [contentProviders, hasSharedExaKey]);

  const currentContentProviderType =
    getCurrentContentProviderType(contentProviders);

  if (searchProvidersError || contentProvidersError) {
    const message =
      searchProvidersError?.message ||
      contentProvidersError?.message ||
      t("failedToLoad");

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
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description={t("description")}
          separator
        />
        <SettingsLayouts.Body>
          <Callout type="danger" title={t("failedToLoadTitle")}>
            {message}
            {detail && (
              <Text as="p" className="mt-2 text-text-03" mainContentBody text03>
                {detail}
              </Text>
            )}
          </Callout>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  if (isLoading) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description={t("description")}
          separator
        />
        <SettingsLayouts.Body>
          <ThreeDotsLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
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

    const existingProviderId = searchModal.existingProviderId;
    const existingProvider = existingProviderId
      ? searchProviders.find((p) => p.id === existingProviderId)
      : null;

    const providerRequiresApiKey =
      searchProviderRequiresApiKey(selectedProviderType);
    const apiKeyChangedForProvider =
      providerRequiresApiKey &&
      searchModal.apiKeyValue !== MASKED_API_KEY_PLACEHOLDER &&
      searchProviderValues.apiKey.length > 0;

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
      mutate: async () => {
        await mutateSearchProviders();
        if (selectedProviderType === "exa") {
          await mutateContentProviders();
        }
      },
    });
  };

  const handleActivateSearchProvider = async (providerId: number) => {
    setActivationError(null);
    try {
      await activateSearchProvider(providerId);
      await mutateSearchProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("unexpectedError");
      setActivationError(message);
    }
  };

  const handleDeactivateSearchProvider = async (providerId: number) => {
    setActivationError(null);
    try {
      await deactivateSearchProvider(providerId);
      await mutateSearchProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("unexpectedError");
      setActivationError(message);
    }
  };

  const handleActivateContentProvider = async (
    provider: WebContentProviderView
  ) => {
    setContentActivationError(null);
    try {
      await activateContentProvider(provider);
      await mutateContentProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("unexpectedError");
      setContentActivationError(message);
    }
  };

  const handleDeactivateContentProvider = async (
    providerId: number,
    providerType: string
  ) => {
    setContentActivationError(null);
    try {
      await deactivateContentProvider(providerId, providerType);
      await mutateContentProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("unexpectedError");
      setContentActivationError(message);
    }
  };

  const handleContentConnect = async () => {
    if (!selectedContentProviderType) {
      return;
    }

    const config = buildContentProviderConfig(
      selectedContentProviderType,
      contentProviderValues.config
    );

    const existingProviderId = contentModal.existingProviderId;
    const existingProvider = existingProviderId
      ? contentProviders.find((p) => p.id === existingProviderId)
      : null;

    const storedBaseUrl = getSingleContentConfigFieldValueForForm(
      selectedContentProviderType,
      existingProvider,
      "https://api.firecrawl.dev/v2/scrape"
    );
    const configChanged =
      selectedContentProviderType === "firecrawl" &&
      storedBaseUrl !== contentProviderValues.config;

    dispatchContentModal({ type: "SET_PHASE", phase: "saving" });
    dispatchContentModal({ type: "CLEAR_MESSAGE" });

    const apiKeyChangedForContentProvider =
      contentModal.apiKeyValue !== MASKED_API_KEY_PLACEHOLDER &&
      contentProviderValues.apiKey.length > 0;

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
      apiKeyChangedForProvider: apiKeyChangedForContentProvider,
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
      mutate: async () => {
        await mutateContentProviders();
        if (selectedContentProviderType === "exa") {
          await mutateSearchProviders();
        }
      },
    });
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
      return t("validatingApiKey");
    }

    const providerName = selectedContentProviderType
      ? CONTENT_PROVIDER_DETAILS[selectedContentProviderType]?.label ||
        selectedContentProviderType
      : "";

    if (selectedContentProviderType === "exa") {
      return t("pasteApiKeyFromExa");
    }

    return selectedContentProviderType === "firecrawl"
      ? t("pasteApiKeyFromFirecrawl")
      : t("pasteApiKeyFromProvider", { provider: providerName });
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

  const handleDisconnectProvider = async () => {
    if (!disconnectTarget) return;
    const { id, category } = disconnectTarget;

    try {
      await disconnectProvider(id, category, replacementProviderId);
      toast.success(t("disconnected", { label: disconnectTarget.label }));
      await mutateSearchProviders();
      await mutateContentProviders();
    } catch (error) {
      console.error("Failed to disconnect web search provider:", error);
      const message =
        error instanceof Error ? error.message : t("unexpectedError");
      if (category === "search") {
        setActivationError(message);
      } else {
        setContentActivationError(message);
      }
    } finally {
      setDisconnectTarget(null);
      setReplacementProviderId(null);
    }
  };

  return (
    <>
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description={t("description")}
          separator
        />

        <SettingsLayouts.Body>
          <div className="flex w-full flex-col gap-3">
            <Content
              title={t("searchEngine")}
              description={t("searchEngineDescription")}
              sizePreset="main-content"
              variant="section"
            />

            {activationError && (
              <Callout type="danger" title={t("unableToUpdateProvider")}>
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
                      ? t("selectSearchEngine")
                      : t("connectSearchEngine")}
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
                  const providerId = provider?.id;
                  const canOpenModal =
                    isBuiltInSearchProviderType(providerType);

                  const status: "disconnected" | "connected" | "selected" =
                    !isConfigured
                      ? "disconnected"
                      : isActive
                        ? "selected"
                        : "connected";

                  return (
                    <ProviderCard
                      key={`${key}-${providerType}`}
                      icon={() =>
                        logoSrc ? (
                          <Image
                            src={logoSrc}
                            alt={`${label} logo`}
                            width={16}
                            height={16}
                          />
                        ) : (
                          <SvgGlobe size={16} />
                        )
                      }
                      title={label}
                      description={subtitle}
                      status={status}
                      onConnect={
                        canOpenModal
                          ? () => {
                              openSearchModal(providerType, provider);
                              setActivationError(null);
                            }
                          : undefined
                      }
                      onSelect={
                        providerId
                          ? () => {
                              void handleActivateSearchProvider(providerId);
                            }
                          : undefined
                      }
                      onDeselect={
                        providerId
                          ? () => {
                              void handleDeactivateSearchProvider(providerId);
                            }
                          : undefined
                      }
                      onEdit={
                        isConfigured && canOpenModal
                          ? () => {
                              openSearchModal(
                                providerType as WebSearchProviderType,
                                provider
                              );
                            }
                          : undefined
                      }
                      onDisconnect={
                        isConfigured && provider && provider.id > 0
                          ? () =>
                              setDisconnectTarget({
                                id: provider.id,
                                label,
                                category: "search",
                                providerType,
                              })
                          : undefined
                      }
                    />
                  );
                }
              )}
            </div>
          </div>

          <div className="flex w-full flex-col gap-3">
            <Content
              title={t("webCrawler")}
              description={t("webCrawlerDescription")}
              sizePreset="main-content"
              variant="section"
            />

            {contentActivationError && (
              <Callout type="danger" title={t("unableToUpdateCrawler")}>
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

                const status: "disconnected" | "connected" | "selected" =
                  !isConfigured
                    ? "disconnected"
                    : isCurrentCrawler
                      ? "selected"
                      : "connected";

                const canActivate =
                  providerId > 0 ||
                  provider.provider_type === "onyx_web_crawler" ||
                  isConfigured;

                const contentLogoSrc =
                  CONTENT_PROVIDER_DETAILS[provider.provider_type]?.logoSrc;

                return (
                  <ProviderCard
                    key={`${provider.provider_type}-${provider.id}`}
                    icon={() =>
                      contentLogoSrc ? (
                        <Image
                          src={contentLogoSrc}
                          alt={`${label} logo`}
                          width={16}
                          height={16}
                        />
                      ) : provider.provider_type === "onyx_web_crawler" ? (
                        <SvgOnyxLogo size={16} />
                      ) : (
                        <SvgGlobe size={16} />
                      )
                    }
                    title={label}
                    description={subtitle}
                    status={status}
                    selectedLabel={t("currentCrawler")}
                    onConnect={() => {
                      openContentModal(provider.provider_type, provider);
                      setContentActivationError(null);
                    }}
                    onSelect={
                      canActivate
                        ? () => {
                            void handleActivateContentProvider(provider);
                          }
                        : undefined
                    }
                    onDeselect={() => {
                      void handleDeactivateContentProvider(
                        providerId,
                        provider.provider_type
                      );
                    }}
                    onEdit={
                      provider.provider_type !== "onyx_web_crawler" &&
                      isConfigured
                        ? () => {
                            openContentModal(provider.provider_type, provider);
                          }
                        : undefined
                    }
                    onDisconnect={
                      provider.provider_type !== "onyx_web_crawler" &&
                      isConfigured &&
                      provider.id > 0
                        ? () =>
                            setDisconnectTarget({
                              id: provider.id,
                              label,
                              category: "content",
                              providerType: provider.provider_type,
                            })
                        : undefined
                    }
                  />
                );
              })}
            </div>
          </div>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      {disconnectTarget && (
        <WebSearchDisconnectModal
          disconnectTarget={disconnectTarget}
          searchProviders={searchProviders}
          contentProviders={combinedContentProviders}
          replacementProviderId={replacementProviderId}
          onReplacementChange={setReplacementProviderId}
          onClose={() => {
            setDisconnectTarget(null);
            setReplacementProviderId(null);
          }}
          onDisconnect={() => void handleDisconnectProvider()}
        />
      )}

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
        isStoredApiKey={searchModal.apiKeyValue === MASKED_API_KEY_PLACEHOLDER}
        optionalField={
          selectedProviderType === "google_pse"
            ? {
                label: t("searchEngineId"),
                value: searchModal.configValue,
                onChange: (value) =>
                  dispatchSearchModal({ type: "SET_CONFIG_VALUE", value }),
                placeholder: t("enterSearchEngineId"),
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
                  label: t("searxngBaseUrl"),
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
            t("checkingConnection")
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
              <SvgOnyxLogo size={24} />
            ) : undefined,
          size: 24,
          containerSize: 28,
        })}
        description={
          selectedContentProviderType
            ? CONTENT_PROVIDER_DETAILS[selectedContentProviderType]
                ?.description ||
              CONTENT_PROVIDER_DETAILS[selectedContentProviderType]?.subtitle ||
              t("provideCredentialsFor", { provider: contentProviderLabel })
            : ""
        }
        apiKeyValue={contentModal.apiKeyValue}
        onApiKeyChange={(value) =>
          dispatchContentModal({ type: "SET_API_KEY", value })
        }
        isStoredApiKey={contentModal.apiKeyValue === MASKED_API_KEY_PLACEHOLDER}
        optionalField={
          selectedContentProviderType === "firecrawl"
            ? {
                label: t("apiBaseUrl"),
                value: contentModal.configValue,
                onChange: (value) =>
                  dispatchContentModal({ type: "SET_CONFIG_VALUE", value }),
                placeholder: "https://",
                description: t("yourApiBaseUrl"),
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
