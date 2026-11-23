"use client";

import { PageLoader } from "@opal/loaders";
import { useState, useMemo, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { useLabelBadge } from "@/lib/badges/components";
import { Hoverable } from "@opal/core";
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
  Card,
  Collapsible,
  Divider,
  InputSingleSelect,
  MessageCard,
  SelectCard,
  Text,
  useCreateModal,
  type SelectDivider,
} from "@opal/components";
import {
  CardGrid,
  ConfirmationModalLayout,
  Content,
  ContentAction,
  ReverseContent,
  IllustrationContent,
  InputHorizontal,
  Section,
  toast,
} from "@opal/layouts";
import { SvgDisconnected, SvgEmpty } from "@opal/illustrations";
import {
  SvgArrowExchange,
  SvgCheckCircle,
  SvgSettings,
  SvgSlash,
  SvgUnplug,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { markdown } from "@opal/utils";
import { getImageGenForm } from "@/views/admin/ImageGenerationPage/forms";
import { getModelIcon } from "@/lib/languageModels/utils";
import { resolveModelDisplayName } from "@/lib/languageModels/hooks";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import type { ModelOptionProvider } from "@/lib/languageModels/types";

const NO_DEFAULT_VALUE = "__none__";

interface DisconnectTarget {
  image_provider_id: string;
  title: string;
  llmProviderOwned: boolean;
  /** Whether it is the default. Tracks the live default while the confirm is
   *  open and freezes on close, so the copy holds while the card fades out. */
  isDefault: boolean;
}

/** A linked model's name, as every model list shows it. */
function linkedModelTitle(
  model: Pick<
    ImageGenerationProviderModel,
    "name" | "display_name" | "custom_display_name"
  >
): string {
  return resolveModelDisplayName(model);
}

interface ConnectedModelCardProps {
  icon: IconFunctionComponent;
  title: string;
  description: string;
  ariaLabel: string;
  isDefault: boolean;
  /** Keeps the disconnect button shown while its confirm is open. */
  disconnecting: boolean;
  onDisconnect: () => void;
  /** Edits an own-key model's credentials; linked models have none. */
  onEdit?: () => void;
}

/** A connected model, as the Language Models page shows a provider. A click
 *  disconnects it, as its unplug button does. The default is set only in the
 *  Image Generation Model select. */
function ConnectedModelCard({
  icon,
  title,
  description,
  ariaLabel,
  isDefault,
  disconnecting,
  onDisconnect,
  onEdit,
}: ConnectedModelCardProps) {
  const t = useTranslations("admin.shared");
  const defaultBadge = useLabelBadge("default");
  return (
    <Hoverable.Root
      group="ImageGenConnectedModel"
      interaction={disconnecting ? "hover" : "rest"}
    >
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
          badge={isDefault ? defaultBadge : undefined}
          rightChildren={
            <Section flexDirection="row" width="fit" height="fit" gap={0}>
              <Hoverable.Item
                group="ImageGenConnectedModel"
                variant="appear-on-hover"
              >
                <Button
                  icon={SvgUnplug}
                  prominence="tertiary"
                  aria-label={t("providerCard.disconnectButton.ariaLabel", {
                    title,
                  })}
                  onClick={(e) => {
                    e.stopPropagation();
                    onDisconnect();
                  }}
                />
              </Hoverable.Item>
              {onEdit && (
                <Button
                  icon={SvgSettings}
                  prominence="tertiary"
                  aria-label={t("providerCard.editButton.ariaLabel", {
                    title,
                  })}
                  onClick={(e) => {
                    e.stopPropagation();
                    onEdit();
                  }}
                />
              )}
            </Section>
          }
        />
      </SelectCard>
    </Hoverable.Root>
  );
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

function configGroups(
  configs: ImageGenerationConfigView[],
  configTitle: (config: ImageGenerationConfigView) => string
): SelectDivider[] {
  const groups = new Map<string, ImageGenerationConfigView[]>();
  for (const config of configs) {
    const name = config.llm_provider_name ?? config.llm_provider_type;
    groups.set(name, [...(groups.get(name) ?? []), config]);
  }
  return Array.from(groups.entries()).map(([title, groupConfigs]) => ({
    title,
    options: groupConfigs.map((c) => ({
      value: c.image_provider_id,
      title: configTitle(c),
      icon: getModelIcon(c.llm_provider_type, c.model_name),
    })),
  }));
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
  const [disconnectProvider, setDisconnectProvider] =
    useState<DisconnectTarget | null>(null);
  const [replacementProviderId, setReplacementProviderId] = useState<
    string | null
  >(null);
  // The target stays set on close so the modal can animate out; opening resets it.
  const disconnectModal = useCreateModal();

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

  // The connected models as the shared model selector takes them, one
  // provider per LLM provider row.
  const selectorProviders = useMemo((): ModelOptionProvider[] => {
    const byProvider = new Map<number, ModelOptionProvider>();
    for (const config of configs) {
      const provider = byProvider.get(config.llm_provider_id) ?? {
        id: config.llm_provider_id,
        name: config.llm_provider_name,
        provider: config.llm_provider_type,
        model_configurations: [],
      };
      provider.model_configurations.push({
        id: config.model_configuration_id,
        name: config.model_name,
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: false,
        supports_reasoning: false,
        display_name: config.display_name,
        custom_display_name: config.custom_display_name,
        effectiveDisplayName: configTitle(config),
      });
      byProvider.set(config.llm_provider_id, provider);
    }
    return [...byProvider.values()];
  }, [configs, configTitle]);

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

  const handleDeselect = async (imageProviderId: string | null) => {
    const config = configs.find((c) => c.image_provider_id === imageProviderId);
    if (config) {
      try {
        await unsetDefaultImageGenerationConfig(config.image_provider_id);
        refetchConfigs();
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : t("deselectError.message")
        );
      }
    }
  };

  // Only the default asks first: it needs a replacement default (or none).
  // Any other model disconnects at once.
  const openDisconnect = async (config: ImageGenerationConfigView) => {
    if (defaultConfig?.image_provider_id !== config.image_provider_id) {
      try {
        await deleteImageGenerationConfig(config.image_provider_id);
        refetchAll();
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : t("disconnectError.message")
        );
      }
      return;
    }
    setDisconnectProvider({
      image_provider_id: config.image_provider_id,
      title: configTitle(config),
      llmProviderOwned: config.llm_provider_owned,
      isDefault: defaultConfig?.image_provider_id === config.image_provider_id,
    });
    setReplacementProviderId(null);
    disconnectModal.toggle(true);
  };

  const handleEdit = (provider: ImageProvider) => {
    const config = configs.find(
      (c) => c.image_provider_id === provider.image_provider_id
    );
    setEditConfig(config || null);
    setActiveProvider(provider);
    modal.toggle(true);
  };

  const handleDisconnect = async () => {
    if (!disconnectProvider) return;
    try {
      // If a replacement was selected (not "No Default"), activate it first
      if (replacementProviderId && replacementProviderId !== NO_DEFAULT_VALUE) {
        await setDefaultImageGenerationConfig(replacementProviderId);
      }

      await deleteImageGenerationConfig(disconnectProvider.image_provider_id);
      refetchAll();
    } catch (error) {
      console.error("Failed to disconnect image generation provider:", error);
      toast.error(
        error instanceof Error ? error.message : t("disconnectError.message")
      );
    } finally {
      disconnectModal.toggle(false);
    }
  };

  const handleModalSuccess = () => {
    setEditConfig(null);
    refetchConfigs();
  };

  // Compute replacement options when disconnecting an active provider
  const isDisconnectingDefault = disconnectProvider?.isDefault;

  const replacementGroups = useMemo(() => {
    if (!disconnectProvider) return [];
    return configGroups(
      configs.filter(
        (c) => c.image_provider_id !== disconnectProvider.image_provider_id
      ),
      configTitle
    );
  }, [disconnectProvider, configs, configTitle]);

  const needsReplacement = !!isDisconnectingDefault;
  const hasReplacements = replacementGroups.length > 0;

  // Auto-select first replacement when modal opens
  useEffect(() => {
    if (needsReplacement && !replacementProviderId && hasReplacements) {
      const firstOption = replacementGroups[0]?.options[0];
      if (firstOption) setReplacementProviderId(firstOption.value);
    }
  }, [disconnectProvider]);

  // Follow the live default while the confirm is open, so a default that
  // changes meanwhile still asks for a replacement. Closing freezes it, so the
  // copy holds while the card fades out.
  useEffect(() => {
    if (!disconnectModal.isOpen || !disconnectProvider) return;
    const isDefault =
      defaultConfig?.image_provider_id === disconnectProvider.image_provider_id;
    if (isDefault !== disconnectProvider.isDefault) {
      setDisconnectProvider({ ...disconnectProvider, isDefault });
    }
  }, [disconnectModal.isOpen, disconnectProvider, defaultConfig]);

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

  const handleDefaultChange = (modelConfigurationId: number | null) => {
    const config = configs.find(
      (c) => c.model_configuration_id === modelConfigurationId
    );
    if (config) {
      void handleSelect(config.image_provider_id);
    } else if (defaultConfig) {
      void handleDeselect(defaultConfig.image_provider_id);
    }
  };

  const noDefaultOption = {
    value: NO_DEFAULT_VALUE,
    title: t("disconnectModal.noDefaultOption.label"),
    description: t("disconnectModal.noDefaultOption.description"),
    icon: SvgSlash,
  };

  return (
    <>
      {configs.length > 0 ? (
        <Card border="solid" rounding={4}>
          <InputHorizontal
            title={t("model.title")}
            description={t("model.description")}
            center
            withLabel
          >
            <SimpleModelSelector
              providers={selectorProviders}
              value={defaultConfig?.model_configuration_id ?? null}
              onChange={handleDefaultChange}
              nullable
              globalDefault={{
                label: t("disconnectModal.noDefaultOption.label"),
                description: t("disconnectModal.noDefaultOption.description"),
              }}
              placeholder={t("model.placeholder")}
            />
          </InputHorizontal>
        </Card>
      ) : (
        <MessageCard variant="info" title={t("emptyState.title")} />
      )}

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

      {configs.length > 0 && (
        <>
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
              {configs.map((config) => {
                const imageProviderId = config.image_provider_id;
                const legacyProvider = config.llm_provider_owned
                  ? legacyProviderById.get(imageProviderId)
                  : undefined;
                const title = configTitle(config);
                const providerName =
                  config.llm_provider_name ?? config.llm_provider_type;
                return (
                  <ConnectedModelCard
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
                    ariaLabel={
                      config.llm_provider_owned
                        ? `image-gen-provider-${imageProviderId}`
                        : `image-gen-model-${config.llm_provider_id}-${config.model_name}`
                    }
                    isDefault={config.is_default}
                    disconnecting={
                      disconnectModal.isOpen &&
                      disconnectProvider?.image_provider_id === imageProviderId
                    }
                    onDisconnect={() => void openDisconnect(config)}
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
        </>
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
                              if (config) void openDisconnect(config);
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

      <disconnectModal.Provider>
        {disconnectProvider && (
          <ConfirmationModalLayout
            icon={SvgUnplug}
            title={markdown(
              t("disconnectModal.header.title", {
                title: disconnectProvider.title,
              })
            )}
            description={
              disconnectProvider.llmProviderOwned
                ? t("disconnectModal.header.description")
                : t("disconnectModal.linkedHeader.description")
            }
            onClose={() => disconnectModal.toggle(false)}
            submit={
              <Button
                variant="danger"
                onClick={() => void handleDisconnect()}
                disabled={
                  needsReplacement && hasReplacements && !replacementProviderId
                }
              >
                {t("disconnectModal.submitButton.label")}
              </Button>
            }
          >
            {needsReplacement ? (
              hasReplacements ? (
                <Section alignItems="start">
                  <Text as="p" color="text-03">
                    {markdown(
                      t("disconnectModal.defaultWithReplacement.description", {
                        title: disconnectProvider.title,
                      })
                    )}
                  </Text>
                  <Section alignItems="start" gap={1}>
                    <Text as="p" color="text-04">
                      {t("disconnectModal.replacement.label")}
                    </Text>
                    <InputSingleSelect
                      value={replacementProviderId ?? ""}
                      onValueChange={(v) => setReplacementProviderId(v)}
                      placeholder={t("disconnectModal.replacement.placeholder")}
                      options={[...replacementGroups, noDefaultOption]}
                    />
                  </Section>
                </Section>
              ) : (
                <>
                  <Text as="p" color="text-03">
                    {markdown(
                      t("disconnectModal.defaultNoReplacement.description", {
                        title: disconnectProvider.title,
                      })
                    )}
                  </Text>
                  <Text as="p" color="text-03">
                    {t("disconnectModal.connectAnother.description")}
                  </Text>
                </>
              )
            ) : (
              <>
                <Text as="p" color="text-03">
                  {markdown(
                    t("disconnectModal.nonDefault.description", {
                      title: disconnectProvider.title,
                    })
                  )}
                </Text>
                <Text as="p" color="text-03">
                  {t("disconnectModal.sessionHistory.description")}
                </Text>
              </>
            )}
          </ConfirmationModalLayout>
        )}
      </disconnectModal.Provider>

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
