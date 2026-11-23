"use client";

import { PageLoader } from "@opal/loaders";
import { useState, useMemo, useCallback } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  IMAGE_PROVIDER_GROUPS,
  ImageProvider,
} from "@/views/admin/ImageGenerationPage/constants";
import {
  ImageGenerationConfigView,
  ImageGenerationLLMProvider,
  ImageGenerationProviderModel,
  linkImageGenerationModel,
  setDefaultImageGenerationConfig,
  unsetDefaultImageGenerationConfig,
  deleteImageGenerationConfig,
} from "@/views/admin/ImageGenerationPage/svc";
import {
  Button,
  Collapsible,
  Divider,
  MessageCard,
  SelectCard,
  Text,
  useCreateModal,
} from "@opal/components";
import {
  CardGrid,
  Content,
  ContentAction,
  ReverseContent,
  IllustrationContent,
  Section,
  toast,
} from "@opal/layouts";
import { SvgDisconnected, SvgEmpty } from "@opal/illustrations";
import { SvgArrowExchange, SvgCheckCircle } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { getImageGenForm } from "@/views/admin/ImageGenerationPage/forms";
import { getModelIcon } from "@/lib/languageModels/utils";
import { resolveModelDisplayName } from "@/lib/languageModels/hooks";
import ProviderCard from "@/sections/admin/ProviderCard";

/** A linked model's name, as every model list shows it. */
function linkedModelTitle(
  model: Pick<
    ImageGenerationProviderModel,
    "name" | "display_name" | "custom_display_name"
  >
): string {
  return resolveModelDisplayName(model);
}

interface AvailableModelCardProps {
  icon: IconFunctionComponent;
  title: string;
  description: string;
  ariaLabel: string;
  /** Already connected: a filled card that says so. */
  connected: boolean;
  onConnect: () => void;
  /** Disconnects a connected model. */
  onDisconnect?: () => void;
}

/** A model of a provider, as the Language Models page shows a new provider.
 *  A connected model stays in the grid, filled, and disconnects on click. */
function AvailableModelCard({
  icon,
  title,
  description,
  ariaLabel,
  connected,
  onConnect,
  onDisconnect,
}: AvailableModelCardProps) {
  const t = useTranslations("admin.shared");
  const tPage = useTranslations("admin.imageGeneration");

  // A connected model's card is filled, says so, and disconnects on click,
  // as its card under Available Models does.
  if (connected) {
    return (
      <SelectCard
        state="filled"
        padding={2}
        rounding={4}
        aria-label={ariaLabel}
        onClick={onDisconnect}
      >
        <ContentAction
          font="main-ui-action"
          icon={icon}
          title={title}
          description={description}
          titleMaxLines={1}
          descriptionMaxLines={1}
          padding={2}
          rightChildren={
            <Section
              flexDirection="row"
              justifyContent="end"
              alignItems="start"
              width="fit"
              height="fit"
              padding={2}
            >
              <ReverseContent
                font="main-ui-body"
                icon={SvgCheckCircle}
                title={tPage("availableModels.connected.label")}
                color="success"
                titleColor="text-03"
              />
            </Section>
          }
        />
      </SelectCard>
    );
  }

  return (
    <SelectCard
      state="empty"
      padding={2}
      rounding={4}
      aria-label={ariaLabel}
      onClick={onConnect}
    >
      <ContentAction
        font="main-ui-action"
        icon={icon}
        title={title}
        description={description}
        titleMaxLines={1}
        descriptionMaxLines={1}
        padding={2}
        rightChildren={
          <Button
            rightIcon={SvgArrowExchange}
            prominence="tertiary"
            onClick={(e) => {
              e.stopPropagation();
              onConnect();
            }}
          >
            {t("providerCard.connectButton.label")}
          </Button>
        }
      />
    </SelectCard>
  );
}

export default function ImageGenerationContent() {
  const t = useTranslations("admin.imageGeneration");
  const {
    data: configs = [],
    error: configError,
    isLoading: configsLoading,
    mutate: refetchConfigs,
  } = useSWR<ImageGenerationConfigView[]>(
    SWR_KEYS.imageGenConfig,
    errorHandlingFetcher
  );

  const {
    data: llmProviders = [],
    error: llmProvidersError,
    isLoading: llmProvidersLoading,
    mutate: refetchLlmProviders,
  } = useSWR<ImageGenerationLLMProvider[]>(
    SWR_KEYS.imageGenLlmProviders,
    errorHandlingFetcher
  );
  const [linkingModelKey, setLinkingModelKey] = useState<string | null>(null);

  const modal = useCreateModal();
  const [activeProvider, setActiveProvider] = useState<ImageProvider | null>(
    null
  );
  const [editConfig, setEditConfig] =
    useState<ImageGenerationConfigView | null>(null);

  const connectedProviderIds = useMemo(() => {
    return new Set(configs.map((c) => c.image_provider_id));
  }, [configs]);

  // Own-key configs from before image models came from LLM providers. They
  // stay until an admin disconnects them.
  const legacyProviderById = useMemo(() => {
    const providers = new Map<string, ImageProvider>();
    for (const group of IMAGE_PROVIDER_GROUPS) {
      for (const p of group.providers) providers.set(p.image_provider_id, p);
    }
    return providers;
  }, []);

  const configTitle = useCallback(
    (config: ImageGenerationConfigView): string =>
      (config.llm_provider_owned
        ? legacyProviderById.get(config.image_provider_id)?.title
        : undefined) ??
      linkedModelTitle({
        name: config.model_name,
        display_name: config.display_name,
        custom_display_name: config.custom_display_name,
      }),
    [legacyProviderById]
  );

  const connectedDeprecatedProviders = useMemo(() => {
    return IMAGE_PROVIDER_GROUPS.flatMap((group) => group.providers).filter(
      (p) => p.deprecated && connectedProviderIds.has(p.image_provider_id)
    );
  }, [connectedProviderIds]);

  const defaultConfig = useMemo(() => {
    return configs.find((c) => c.is_default);
  }, [configs]);

  const refetchAll = () => {
    refetchConfigs();
    refetchLlmProviders();
  };

  const handleLink = async (
    llmProvider: ImageGenerationLLMProvider,
    model: ImageGenerationProviderModel
  ) => {
    if (linkingModelKey !== null) return;
    const modelKey = `${llmProvider.llm_provider_id}:${model.name}`;
    setLinkingModelKey(modelKey);
    try {
      await linkImageGenerationModel(
        llmProvider.llm_provider_id,
        model.name,
        !defaultConfig
      );
      await Promise.all([refetchConfigs(), refetchLlmProviders()]);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("linkError.message")
      );
    } finally {
      setLinkingModelKey(null);
    }
  };

  const handleSelect = async (imageProviderId: string | null) => {
    const config = configs.find((c) => c.image_provider_id === imageProviderId);
    if (config) {
      try {
        await setDefaultImageGenerationConfig(config.image_provider_id);
        refetchConfigs();
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : t("setDefaultError.message")
        );
      }
    }
  };

  // Disconnects at once, also the default: image generation is then off
  // until another model is the default.
  const disconnectModel = async (config: ImageGenerationConfigView) => {
    try {
      await deleteImageGenerationConfig(config.image_provider_id);
      refetchAll();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("disconnectError.message")
      );
    }
  };

  const handleDeselect = async (imageProviderId: string) => {
    try {
      await unsetDefaultImageGenerationConfig(imageProviderId);
      refetchConfigs();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("deselectError.message")
      );
    }
  };

  const handleEdit = (provider: ImageProvider) => {
    const config = configs.find(
      (c) => c.image_provider_id === provider.image_provider_id
    );
    setEditConfig(config || null);
    setActiveProvider(provider);
    modal.toggle(true);
  };

  const handleModalSuccess = () => {
    setEditConfig(null);
    refetchConfigs();
  };

  // Available Models, alphabetical by the name each card shows.
  const listedConfigs = [...configs].sort((a, b) =>
    configTitle(a).localeCompare(configTitle(b))
  );

  if (configError) {
    return (
      <IllustrationContent
        illustration={SvgDisconnected}
        title={t("loadError.message")}
      />
    );
  }

  if (configsLoading || llmProvidersLoading) {
    return <PageLoader />;
  }

  return (
    <>
      {connectedDeprecatedProviders.map((provider) => (
        <MessageCard
          key={provider.image_provider_id}
          variant="warning"
          title={t("retiredModelWarning.title", { title: provider.title })}
          description={t("retiredModelWarning.description", {
            title: provider.title,
          })}
        />
      ))}

      {/* Image generation is on while a model is the default. */}
      {!defaultConfig && (
        <MessageCard variant="info" title={t("noDefaultWarning.title")} />
      )}

      {listedConfigs.length > 0 && (
        <Section gap={8} height="fit" alignItems="stretch">
          <Section
            gap={3}
            height="fit"
            alignItems="stretch"
            justifyContent="start"
          >
            <Content
              font="main-content-emphasis"
              title={t("connectedModels.title")}
            />
            <Section gap={2} height="fit" alignItems="stretch">
              {listedConfigs.map((config) => {
                const imageProviderId = config.image_provider_id;
                const legacyProvider = config.llm_provider_owned
                  ? legacyProviderById.get(imageProviderId)
                  : undefined;
                const title = configTitle(config);
                const providerName =
                  config.llm_provider_name ?? config.llm_provider_type;
                return (
                  <ProviderCard
                    key={imageProviderId}
                    icon={getModelIcon(
                      config.llm_provider_type,
                      config.model_name
                    )}
                    title={title}
                    description={
                      legacyProvider
                        ? t(legacyProvider.descriptionKey)
                        : providerName
                    }
                    // Connected, or the default, as the Web Search page
                    // shows its providers. A click sets or clears the default.
                    status={config.is_default ? "selected" : "connected"}
                    aria-label={
                      config.llm_provider_owned
                        ? `image-gen-provider-${imageProviderId}`
                        : `image-gen-model-${config.llm_provider_id}-${config.model_name}`
                    }
                    onSelect={() => void handleSelect(imageProviderId)}
                    onDeselect={() => void handleDeselect(imageProviderId)}
                    onDisconnect={() => void disconnectModel(config)}
                    onEdit={
                      legacyProvider
                        ? () => handleEdit(legacyProvider)
                        : undefined
                    }
                  />
                );
              })}
            </Section>
          </Section>
          <Divider paddingParallel={0} paddingPerpendicular={0} />
        </Section>
      )}

      {llmProvidersError ? (
        <MessageCard variant="error" title={t("loadError.message")} />
      ) : (
        <Section
          gap={3}
          height="fit"
          alignItems="stretch"
          justifyContent="start"
        >
          <Content
            font="main-content-emphasis"
            title={t("availableModels.title")}
            description={t("availableModels.description")}
          />
          {llmProviders.length === 0 ? (
            <IllustrationContent
              illustration={SvgEmpty}
              title={t("noImageModels.title")}
              description={t("noImageModels.description")}
            />
          ) : (
            <Section gap={8} height="fit" alignItems="stretch">
              {llmProviders.map((llmProvider) => {
                const providerName =
                  llmProvider.llm_provider_name ?? llmProvider.provider;
                return (
                  <Collapsible
                    key={`llm-${llmProvider.llm_provider_id}`}
                    title={providerName}
                    font="main-ui-action"
                    titleColor="text-03"
                    gapping={2}
                  >
                    <CardGrid>
                      {llmProvider.models.map((model) => {
                        const title = linkedModelTitle(model);
                        return (
                          <AvailableModelCard
                            key={model.name}
                            icon={getModelIcon(
                              llmProvider.provider,
                              model.name
                            )}
                            title={title}
                            description={
                              title === model.name ? providerName : model.name
                            }
                            // Not image-gen-model-…: a connected model's card
                            // under Available Models has that name.
                            ariaLabel={`image-gen-available-${llmProvider.llm_provider_id}-${model.name}`}
                            connected={model.image_provider_id !== null}
                            onDisconnect={() => {
                              const config = configs.find(
                                (c) =>
                                  c.image_provider_id ===
                                  model.image_provider_id
                              );
                              if (config) void disconnectModel(config);
                            }}
                            onConnect={() =>
                              void handleLink(llmProvider, model)
                            }
                          />
                        );
                      })}
                    </CardGrid>
                  </Collapsible>
                );
              })}
            </Section>
          )}
        </Section>
      )}

      {activeProvider && (
        <modal.Provider>
          {getImageGenForm({
            modal: modal,
            imageProvider: activeProvider,
            existingConfig: editConfig || undefined,
            onSuccess: handleModalSuccess,
          })}
        </modal.Provider>
      )}
    </>
  );
}
