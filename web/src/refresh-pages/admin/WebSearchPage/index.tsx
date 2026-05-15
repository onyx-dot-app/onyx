"use client";

import { useMemo, useState } from "react";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Content } from "@opal/layouts";
import ProviderCard from "@/sections/admin/ProviderCard";
import { FetchError } from "@/lib/fetcher";
import { ThreeDotsLoader } from "@/components/Loading";
import { useWebSearchProviders } from "@/lib/webSearch/hooks";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import { SvgGlobe } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import { MessageCard } from "@opal/components";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  WebProviderSetupModal,
  type ProviderModalState,
} from "@/refresh-pages/admin/WebSearchPage/WebProviderSetupModal";
import { WebSearchDisconnectModal } from "@/refresh-pages/admin/WebSearchPage/WebSearchDisconnectModal";
import {
  SEARCH_PROVIDER_DETAILS,
  SEARCH_PROVIDER_ORDER,
  getSearchProviderDisplayLabel,
  isBuiltInSearchProviderType,
  isSearchProviderConfigured,
  CONTENT_PROVIDER_DETAILS,
  CONTENT_PROVIDER_ORDER,
  getCurrentContentProviderType,
  isContentProviderConfigured,
} from "@/lib/webSearch/utils";
import {
  activateSearchProvider,
  deactivateSearchProvider,
  activateContentProvider,
  deactivateContentProvider,
} from "@/lib/webSearch/svc";
import type {
  WebSearchProviderType,
  WebContentProviderType,
  WebSearchProviderView,
  WebContentProviderView,
  DisconnectTargetState,
} from "@/lib/webSearch/types";

const route = ADMIN_ROUTES.WEB_SEARCH;

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function WebSearchPage() {
  const [activeProvider, setActiveProvider] =
    useState<ProviderModalState | null>(null);
  const [disconnectTarget, setDisconnectTarget] =
    useState<DisconnectTargetState | null>(null);
  const setupModal = useCreateModal();
  const disconnectModal = useCreateModal();
  const {
    searchProviders,
    contentProviders,
    searchProvidersError,
    contentProvidersError,
    isLoading,
    mutateSearchProviders,
    mutateContentProviders,
  } = useWebSearchProviders();

  const exaSearchProvider = searchProviders.find(
    (p) => p.provider_type === "exa"
  );
  const exaContentProvider = contentProviders.find(
    (p) => p.provider_type === "exa"
  );
  const openSearchModal = (
    providerType: WebSearchProviderType,
    provider?: WebSearchProviderView
  ) => {
    const hasStoredKey = !!provider?.masked_api_key;
    const isExa = providerType === "exa";
    const sharedExaMaskedKey =
      isExa && !hasStoredKey
        ? (exaContentProvider?.masked_api_key ?? null)
        : null;

    const effectiveProvider: WebSearchProviderView | null =
      provider ??
      (sharedExaMaskedKey
        ? {
            id: -1,
            name: "Exa",
            provider_type: "exa",
            is_active: false,
            config: null,
            masked_api_key: sharedExaMaskedKey,
          }
        : null);

    setActiveProvider({
      category: "search",
      providerType,
      provider: effectiveProvider,
    });
    setupModal.toggle(true);
  };

  const openContentModal = (
    providerType: WebContentProviderType,
    provider?: WebContentProviderView
  ) => {
    setActiveProvider({
      category: "content",
      providerType,
      provider: provider ?? null,
    });
    setupModal.toggle(true);
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
        logo: details.logo,
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
        logo: undefined,
        provider,
      }));

    return [...ordered, ...additional];
  }, [searchProviders]);

  const combinedContentProviders = useMemo(() => {
    const byType = new Map(
      contentProviders.map((p) => [p.provider_type, p] as const)
    );

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
          masked_api_key: null,
        } satisfies WebContentProviderView;
      }

      if (providerType === "firecrawl") {
        return {
          id: -2,
          name: "Firecrawl",
          provider_type: "firecrawl",
          is_active: false,
          config: null,
          masked_api_key: null,
        } satisfies WebContentProviderView;
      }

      if (providerType === "exa") {
        return {
          id: -3,
          name: "Exa",
          provider_type: "exa",
          is_active: false,
          config: null,
          masked_api_key:
            exaSearchProvider?.masked_api_key ??
            exaContentProvider?.masked_api_key ??
            null,
        } satisfies WebContentProviderView;
      }

      return null;
    }).filter(Boolean) as WebContentProviderView[];

    const additional = contentProviders.filter(
      (p) => !CONTENT_PROVIDER_ORDER.includes(p.provider_type)
    );

    return [...ordered, ...additional];
  }, [contentProviders, exaSearchProvider, exaContentProvider]);

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
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description="Search settings for external search across the internet."
          divider
        />
        <SettingsLayouts.Body>
          <MessageCard
            variant="error"
            title="Failed to load web search settings"
            description={detail ?? message}
          />
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
          description="Search settings for external search across the internet."
          divider
        />
        <SettingsLayouts.Body>
          <ThreeDotsLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  async function handleActivateSearchProvider(providerId: number) {
    try {
      await activateSearchProvider(providerId);
      await mutateSearchProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      toast.error(message);
    }
  }

  async function handleDeactivateSearchProvider(providerId: number) {
    try {
      await deactivateSearchProvider(providerId);
      await mutateSearchProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      toast.error(message);
    }
  }

  async function handleActivateContentProvider(
    provider: WebContentProviderView
  ) {
    try {
      await activateContentProvider(provider);
      await mutateContentProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      toast.error(message);
    }
  }

  async function handleDeactivateContentProvider(
    providerId: number,
    providerType: string
  ) {
    try {
      await deactivateContentProvider(providerId, providerType);
      await mutateContentProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      toast.error(message);
    }
  }

  return (
    <>
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description="Search settings for external search across the internet."
          divider
        />

        <SettingsLayouts.Body>
          <div className="flex w-full flex-col gap-3">
            <Content
              title="Search Engine"
              description="External search engine API used for web search result URLs, snippets, and metadata."
              sizePreset="main-content"
              variant="section"
            />

            {!hasActiveSearchProvider && (
              <MessageCard
                variant="info"
                title={
                  hasConfiguredSearchProvider
                    ? "Select a search engine to enable web search."
                    : "Connect a search engine to set up web search."
                }
              />
            )}

            <div className="flex flex-col gap-2">
              {combinedSearchProviders.map(
                ({
                  key,
                  providerType,
                  label,
                  subtitle,
                  logo: Logo,
                  provider,
                }) => {
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
                        Logo ? <Logo size={16} /> : <SvgGlobe size={16} />
                      }
                      title={label}
                      description={subtitle}
                      status={status}
                      onConnect={
                        canOpenModal
                          ? () => openSearchModal(providerType, provider)
                          : undefined
                      }
                      onSelect={
                        providerId
                          ? () => void handleActivateSearchProvider(providerId)
                          : undefined
                      }
                      onDeselect={
                        providerId
                          ? () =>
                              void handleDeactivateSearchProvider(providerId)
                          : undefined
                      }
                      onEdit={
                        isConfigured && canOpenModal
                          ? () =>
                              openSearchModal(
                                providerType as WebSearchProviderType,
                                provider
                              )
                          : undefined
                      }
                      onDisconnect={
                        isConfigured && provider && provider.id > 0
                          ? () => {
                              setDisconnectTarget({
                                id: provider.id,
                                label,
                                category: "search",
                                providerType,
                              });
                              disconnectModal.toggle(true);
                            }
                          : undefined
                      }
                      disconnectModalOpen={
                        disconnectModal.isOpen &&
                        disconnectTarget?.id === providerId &&
                        disconnectTarget?.category === "search"
                      }
                      setupModalOpen={
                        setupModal.isOpen &&
                        activeProvider?.category === "search" &&
                        activeProvider?.providerType === providerType
                      }
                    />
                  );
                }
              )}
            </div>
          </div>

          <div className="flex w-full flex-col gap-3">
            <Content
              title="Web Crawler"
              description="Used to read the full contents of search result pages."
              sizePreset="main-content"
              variant="section"
            />

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

                const ContentLogo =
                  CONTENT_PROVIDER_DETAILS[provider.provider_type]?.logo;

                return (
                  <ProviderCard
                    key={`${provider.provider_type}-${provider.id}`}
                    icon={() =>
                      ContentLogo ? (
                        <ContentLogo size={16} />
                      ) : provider.provider_type === "onyx_web_crawler" ? (
                        <SvgOnyxLogo size={16} />
                      ) : (
                        <SvgGlobe size={16} />
                      )
                    }
                    title={label}
                    description={subtitle}
                    status={status}
                    selectedLabel="Current Crawler"
                    onConnect={() => {
                      openContentModal(provider.provider_type, provider);
                    }}
                    onSelect={
                      canActivate
                        ? () => void handleActivateContentProvider(provider)
                        : undefined
                    }
                    onDeselect={() =>
                      void handleDeactivateContentProvider(
                        providerId,
                        provider.provider_type
                      )
                    }
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
                        ? () => {
                            setDisconnectTarget({
                              id: provider.id,
                              label,
                              category: "content",
                              providerType: provider.provider_type,
                            });
                            disconnectModal.toggle(true);
                          }
                        : undefined
                    }
                    disconnectModalOpen={
                      disconnectModal.isOpen &&
                      disconnectTarget?.id === providerId &&
                      disconnectTarget?.category === "content"
                    }
                    setupModalOpen={
                      setupModal.isOpen &&
                      activeProvider?.category === "content" &&
                      activeProvider?.providerType === provider.provider_type
                    }
                  />
                );
              })}
            </div>
          </div>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      {disconnectTarget && (
        <disconnectModal.Provider>
          <WebSearchDisconnectModal disconnectTarget={disconnectTarget} />
        </disconnectModal.Provider>
      )}

      {activeProvider && (
        <setupModal.Provider>
          <WebProviderSetupModal state={activeProvider} />
        </setupModal.Provider>
      )}
    </>
  );
}
