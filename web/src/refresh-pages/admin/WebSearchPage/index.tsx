"use client";

import { useMemo, useState } from "react";
import { SettingsLayouts } from "@opal/layouts";
import { Content } from "@opal/layouts";
import ProviderCard from "@/sections/admin/ProviderCard";
import { FetchError } from "@/lib/fetcher";
import { ThreeDotsLoader } from "@/components/Loading";
import { useWebSearchProviders } from "@/lib/webSearch/hooks";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import { SvgGlobe } from "@opal/icons";
import { GlomiLogoMark } from "@/refresh-components/GlomiLogo";
import { MessageCard } from "@opal/components";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  WebSearchSetupModal,
  type ProviderModalState,
} from "@/refresh-pages/admin/WebSearchPage/WebSearchSetupModal";
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
        subtitle: "自定义集成",
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
          name: "Glomi AI 网页抓取器",
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
      "无法加载网页搜索配置。";

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
          description="配置用于互联网检索的外部搜索服务。"
          divider
        />
        <SettingsLayouts.Body>
          <MessageCard
            variant="error"
            title="网页搜索设置加载失败"
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
          description="配置用于互联网检索的外部搜索服务。"
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
        error instanceof Error ? error.message : "发生未知错误。";
      toast.error(message);
    }
  }

  async function handleDeactivateSearchProvider(providerId: number) {
    try {
      await deactivateSearchProvider(providerId);
      await mutateSearchProviders();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "发生未知错误。";
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
        error instanceof Error ? error.message : "发生未知错误。";
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
        error instanceof Error ? error.message : "发生未知错误。";
      toast.error(message);
    }
  }

  return (
    <>
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description="配置用于互联网检索的外部搜索服务。"
          divider
        />

        <SettingsLayouts.Body>
          <div className="flex w-full flex-col gap-3">
            <Content
              title="搜索引擎"
              description="用于获取网页搜索结果链接、摘要和元数据的外部搜索引擎 API。"
              sizePreset="main-content"
              variant="section"
            />

            {!hasActiveSearchProvider && (
              <MessageCard
                variant="info"
                title={
                  hasConfiguredSearchProvider
                    ? "请选择一个搜索引擎来启用网页搜索。"
                    : "连接一个搜索引擎来完成网页搜索设置。"
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
              title="网页抓取器"
              description="用于读取搜索结果页面的完整内容。"
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
                        <GlomiLogoMark size={16} />
                      ) : (
                        <SvgGlobe size={16} />
                      )
                    }
                    title={label}
                    description={subtitle}
                    status={status}
                    selectedLabel="当前抓取器"
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
          <WebSearchSetupModal state={activeProvider} />
        </setupModal.Provider>
      )}
    </>
  );
}
