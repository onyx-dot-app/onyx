"use client";

import { useEffect, useMemo, useState } from "react";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Content } from "@opal/layouts";
import ProviderCard from "@/sections/admin/ProviderCard";
import { markdown } from "@opal/utils";
import { FetchError } from "@/lib/fetcher";
import { ThreeDotsLoader } from "@/components/Loading";
import { useWebSearchProviders } from "@/lib/webSearch/hooks";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import { SvgGlobe, SvgSlash, SvgUnplug } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import { Button, MessageCard } from "@opal/components";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  WebProviderSetupModal,
  type ConfigFieldSpec,
} from "@/refresh-pages/admin/WebSearchPage/WebProviderSetupModal";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import {
  SEARCH_PROVIDER_DETAILS,
  SEARCH_PROVIDER_ORDER,
  getSearchProviderDisplayLabel,
  getSingleConfigFieldValueForForm,
  isBuiltInSearchProviderType,
  isSearchProviderConfigured,
  searchProviderRequiresApiKey,
  CONTENT_PROVIDER_DETAILS,
  CONTENT_PROVIDER_ORDER,
  getSingleContentConfigFieldValueForForm,
  getCurrentContentProviderType,
  isContentProviderConfigured,
} from "@/lib/webSearch/utils";
import {
  activateSearchProvider,
  deactivateSearchProvider,
  activateContentProvider,
  deactivateContentProvider,
  disconnectProvider,
} from "@/lib/webSearch/svc";
import type {
  WebSearchProviderType,
  WebContentProviderType,
  WebSearchProviderView,
  WebContentProviderView,
  DisconnectTargetState,
} from "@/lib/webSearch/types";

const NO_DEFAULT_VALUE = "__none__";

const route = ADMIN_ROUTES.WEB_SEARCH;

function getSearchConfigField(
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

function getContentConfigField(
  providerType: string
): ConfigFieldSpec | undefined {
  if (providerType === "firecrawl") {
    return {
      title: "API Base URL",
      placeholder: "https://api.firecrawl.dev/v2/scrape",
      subDescription: "Your Firecrawl API base URL.",
    };
  }
  return undefined;
}

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
  const isSearch = disconnectTarget.category === "search";

  const isActive = isSearch
    ? searchProviders.find((p) => p.id === disconnectTarget.id)?.is_active ??
      false
    : contentProviders.find((p) => p.id === disconnectTarget.id)?.is_active ??
      false;

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

  const categoryLabel = isSearch ? "search engine" : "web crawler";
  const featureLabel = isSearch ? "web search" : "web crawling";
  const disableLabel = isSearch ? "Disable Web Search" : "Disable Web Crawling";

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
      description="This will remove the stored credentials for this provider."
      onClose={onClose}
      submit={
        <Button
          variant="danger"
          onClick={onDisconnect}
          disabled={
            needsReplacement && hasReplacements && !replacementProviderId
          }
        >
          Disconnect
        </Button>
      }
    >
      {needsReplacement ? (
        hasReplacements ? (
          <Section alignItems="start">
            <Text as="p" text03>
              <b>{disconnectTarget.label}</b> is currently the active{" "}
              {categoryLabel}. Search history will be preserved.
            </Text>
            <Section alignItems="start" gap={0.25}>
              <Text as="p" secondaryBody text03>
                Set New Default
              </Text>
              <InputSelect
                value={replacementProviderId ?? undefined}
                onValueChange={(v) => onReplacementChange(v)}
              >
                <InputSelect.Trigger placeholder="Select a replacement provider" />
                <InputSelect.Content>
                  {replacementOptions.map((p) => (
                    <InputSelect.Item key={p.id} value={String(p.id)}>
                      {getLabel(p)}
                    </InputSelect.Item>
                  ))}
                  <InputSelect.Separator />
                  <InputSelect.Item value={NO_DEFAULT_VALUE} icon={SvgSlash}>
                    <span>
                      <b>No Default</b>
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
              <b>{disconnectTarget.label}</b> is currently the active{" "}
              {categoryLabel}.
            </Text>
            <Text as="p" text03>
              Connect another provider to continue using {featureLabel}.
            </Text>
          </>
        )
      ) : (
        <>
          <Text as="p" text03>
            {isSearch ? "Web search" : "Web crawling"} will no longer be routed
            through <b>{disconnectTarget.label}</b>.
          </Text>
          <Text as="p" text03>
            Search history will be preserved.
          </Text>
        </>
      )}
    </ConfirmationModalLayout>
  );
}

// ---------------------------------------------------------------------------
// Local state types
// ---------------------------------------------------------------------------

type ActiveSearchProviderState = {
  providerType: WebSearchProviderType;
  provider: WebSearchProviderView | null;
  hasSharedKey: boolean;
};

type ActiveContentProviderState = {
  providerType: WebContentProviderType;
  provider: WebContentProviderView | null;
  hasSharedKey: boolean;
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function WebSearchPage() {
  const [activeSearchProvider, setActiveSearchProvider] =
    useState<ActiveSearchProviderState | null>(null);
  const [activeContentProvider, setActiveContentProvider] =
    useState<ActiveContentProviderState | null>(null);
  const [disconnectTarget, setDisconnectTarget] =
    useState<DisconnectTargetState | null>(null);
  const [replacementProviderId, setReplacementProviderId] = useState<
    string | null
  >(null);

  const searchSetupModal = useCreateModal();
  const contentSetupModal = useCreateModal();

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
  const hasSharedExaKey =
    (exaSearchProvider?.has_api_key || exaContentProvider?.has_api_key) ??
    false;

  const openSearchModal = (
    providerType: WebSearchProviderType,
    provider?: WebSearchProviderView
  ) => {
    const hasStoredKey = provider?.has_api_key ?? false;
    const isExa = providerType === "exa";
    const canUseSharedExaKey = isExa && hasSharedExaKey && !hasStoredKey;

    setActiveSearchProvider({
      providerType,
      provider: provider ?? null,
      hasSharedKey: canUseSharedExaKey,
    });
    searchSetupModal.toggle(true);
  };

  const openContentModal = (
    providerType: WebContentProviderType,
    provider?: WebContentProviderView
  ) => {
    const realProvider = provider && provider.id > 0 ? provider : null;
    const providerRequiresApiKey = providerType !== "onyx_web_crawler";
    const hasSharedKey =
      providerRequiresApiKey &&
      !realProvider &&
      (provider?.has_api_key ?? false);

    setActiveContentProvider({
      providerType,
      provider: realProvider,
      hasSharedKey,
    });
    contentSetupModal.toggle(true);
  };

  const handleSearchSuccess = () => {
    searchSetupModal.toggle(false);
    toast.success("Provider connected");
  };

  const handleContentSuccess = () => {
    contentSetupModal.toggle(false);
    toast.success("Provider connected");
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

  const handleActivateSearchProvider = async (providerId: number) => {
    try {
      await activateSearchProvider(providerId);
      await mutateSearchProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      toast.error(message);
    }
  };

  const handleDeactivateSearchProvider = async (providerId: number) => {
    try {
      await deactivateSearchProvider(providerId);
      await mutateSearchProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      toast.error(message);
    }
  };

  const handleActivateContentProvider = async (
    provider: WebContentProviderView
  ) => {
    try {
      await activateContentProvider(provider);
      await mutateContentProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      toast.error(message);
    }
  };

  const handleDeactivateContentProvider = async (
    providerId: number,
    providerType: string
  ) => {
    try {
      await deactivateContentProvider(providerId, providerType);
      await mutateContentProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      toast.error(message);
    }
  };

  const handleDisconnectProvider = async () => {
    if (!disconnectTarget) return;
    const { id, category } = disconnectTarget;

    try {
      await disconnectProvider(id, category, replacementProviderId);
      toast.success(`${disconnectTarget.label} disconnected`);
      await mutateSearchProviders();
      await mutateContentProviders();
    } catch (error) {
      console.error("Failed to disconnect web search provider:", error);
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      toast.error(message);
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
                            }
                          : undefined
                      }
                      disconnectModalOpen={
                        disconnectTarget?.id === providerId &&
                        disconnectTarget?.category === "search"
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
                        ? () =>
                            setDisconnectTarget({
                              id: provider.id,
                              label,
                              category: "content",
                              providerType: provider.provider_type,
                            })
                        : undefined
                    }
                    disconnectModalOpen={
                      disconnectTarget?.id === providerId &&
                      disconnectTarget?.category === "content"
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

      <searchSetupModal.Provider>
        {activeSearchProvider && (
          <WebProviderSetupModal
            providerType={activeSearchProvider.providerType}
            category="search"
            providerLabel={getSearchProviderDisplayLabel(
              activeSearchProvider.providerType
            )}
            icon={
              SEARCH_PROVIDER_DETAILS[activeSearchProvider.providerType]?.logo
            }
            apiKeyUrl={
              SEARCH_PROVIDER_DETAILS[activeSearchProvider.providerType]
                ?.apiKeyUrl
            }
            existingProvider={
              activeSearchProvider.provider
                ? {
                    id: activeSearchProvider.provider.id,
                    name: activeSearchProvider.provider.name,
                    has_api_key: activeSearchProvider.provider.has_api_key,
                  }
                : null
            }
            hasSharedApiKey={activeSearchProvider.hasSharedKey}
            initialConfigValue={getSingleConfigFieldValueForForm(
              activeSearchProvider.providerType,
              activeSearchProvider.provider
            )}
            requiresApiKey={searchProviderRequiresApiKey(
              activeSearchProvider.providerType
            )}
            configField={getSearchConfigField(
              activeSearchProvider.providerType
            )}
            mutate={async () => {
              await mutateSearchProviders();
              if (activeSearchProvider.providerType === "exa") {
                await mutateContentProviders();
              }
            }}
            onSuccess={handleSearchSuccess}
          />
        )}
      </searchSetupModal.Provider>

      <contentSetupModal.Provider>
        {activeContentProvider && (
          <WebProviderSetupModal
            providerType={activeContentProvider.providerType}
            category="content"
            providerLabel={
              CONTENT_PROVIDER_DETAILS[activeContentProvider.providerType]
                ?.label ?? activeContentProvider.providerType
            }
            icon={
              CONTENT_PROVIDER_DETAILS[activeContentProvider.providerType]?.logo
            }
            existingProvider={
              activeContentProvider.provider
                ? {
                    id: activeContentProvider.provider.id,
                    name: activeContentProvider.provider.name,
                    has_api_key: activeContentProvider.provider.has_api_key,
                  }
                : null
            }
            hasSharedApiKey={activeContentProvider.hasSharedKey}
            initialConfigValue={
              activeContentProvider.providerType === "firecrawl"
                ? getSingleContentConfigFieldValueForForm(
                    activeContentProvider.providerType,
                    activeContentProvider.provider,
                    "https://api.firecrawl.dev/v2/scrape"
                  )
                : undefined
            }
            requiresApiKey={
              activeContentProvider.providerType !== "onyx_web_crawler"
            }
            configField={getContentConfigField(
              activeContentProvider.providerType
            )}
            mutate={async () => {
              await mutateContentProviders();
              if (activeContentProvider.providerType === "exa") {
                await mutateSearchProviders();
              }
            }}
            onSuccess={handleContentSuccess}
          />
        )}
      </contentSetupModal.Provider>
    </>
  );
}
