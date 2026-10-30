"use client";

import { PageLoader } from "@opal/loaders";
import { useState, useMemo, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
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
  Divider,
  InputSingleSelect,
  MessageCard,
  SelectCard,
  Tabs,
  Text,
  useCreateModal,
  type SelectDivider,
} from "@opal/components";
import {
  CardGrid,
  ConfirmationModalLayout,
  Content,
  ContentAction,
  IllustrationContent,
  InputHorizontal,
  Section,
  toast,
} from "@opal/layouts";
import { Hoverable } from "@opal/core";
import { SvgDisconnected, SvgEmpty } from "@opal/illustrations";
import {
  SvgArrowExchange,
  SvgSettings,
  SvgSlash,
  SvgUnplug,
} from "@opal/icons";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { markdown } from "@opal/utils";
import { getImageGenForm } from "@/views/admin/ImageGenerationPage/forms";
import { getModelIcon } from "@/lib/languageModels/utils";

const NO_DEFAULT_VALUE = "__none__";

type ModelFilter = "recommended" | "all";

interface DisconnectTarget {
  image_provider_id: string;
  title: string;
  llmProviderOwned: boolean;
}

function linkedModelTitle(model: ImageGenerationProviderModel): string {
  return model.display_name || model.name;
}

interface ConnectedModelCardProps {
  icon: IconFunctionComponent;
  title: string | RichStr;
  description: string | RichStr;
  ariaLabel: string;
  isDefault: boolean;
  disconnectModalOpen: boolean;
  onDisconnect: () => void;
  onEdit?: () => void;
}

function ConnectedModelCard({
  icon,
  title,
  description,
  ariaLabel,
  isDefault,
  disconnectModalOpen,
  onDisconnect,
  onEdit,
}: ConnectedModelCardProps) {
  const t = useTranslations("admin.imageGeneration");
  const ariaTitle = typeof title === "string" ? title : title.raw;
  return (
    <Hoverable.Root
      group="ConnectedImageModelCard"
      interaction={disconnectModalOpen ? "hover" : "rest"}
    >
      <SelectCard
        state="filled"
        padding={2}
        rounding={4}
        aria-label={ariaLabel}
        onClick={onEdit}
      >
        <ContentAction
          icon={icon}
          title={title}
          description={description}
          titleMaxLines={1}
          descriptionMaxLines={1}
          sizePreset="main-ui"
          variant="section"
          padding={2}
          tag={
            isDefault
              ? { title: t("defaultTag.label"), color: "blue" }
              : undefined
          }
          rightChildren={
            <Section flexDirection="row" width="fit" height="fit" gap={0}>
              <Hoverable.Item
                group="ConnectedImageModelCard"
                variant="appear-on-hover"
              >
                <Button
                  icon={SvgUnplug}
                  prominence="tertiary"
                  aria-label={t("disconnectButton.ariaLabel", {
                    title: ariaTitle,
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
                  aria-label={t("editButton.ariaLabel", { title: ariaTitle })}
                  tabIndex={-1}
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
  title: string | RichStr;
  description: string | RichStr;
  ariaLabel: string;
  disabled: boolean;
  onConnect: () => void;
}

function AvailableModelCard({
  icon,
  title,
  description,
  ariaLabel,
  disabled,
  onConnect,
}: AvailableModelCardProps) {
  const t = useTranslations("admin.imageGeneration");
  return (
    <Card border="solid" padding={2} rounding={4} aria-label={ariaLabel}>
      <ContentAction
        icon={icon}
        title={title}
        description={description}
        titleMaxLines={1}
        descriptionMaxLines={1}
        sizePreset="main-ui"
        variant="section"
        padding={2}
        rightChildren={
          <Button
            rightIcon={SvgArrowExchange}
            prominence="tertiary"
            disabled={disabled}
            onClick={onConnect}
          >
            {t("connectButton.label")}
          </Button>
        }
      />
    </Card>
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
  const router = useRouter();
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
  const [modelFilter, setModelFilter] = useState<ModelFilter>("recommended");
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

  const availableGroups = useMemo(() => {
    return llmProviders
      .map((llmProvider) => ({
        ...llmProvider,
        models: llmProvider.models.filter(
          (m) =>
            !m.image_provider_id && (modelFilter === "all" || m.is_recommended)
        ),
      }))
      .filter((group) => group.models.length > 0);
  }, [llmProviders, modelFilter]);

  const titleByImageProviderId = useMemo(() => {
    const titles = new Map<string, string>();
    for (const group of IMAGE_PROVIDER_GROUPS) {
      for (const p of group.providers) titles.set(p.image_provider_id, p.title);
    }
    for (const llmProvider of llmProviders) {
      for (const m of llmProvider.models) {
        if (m.image_provider_id)
          titles.set(m.image_provider_id, linkedModelTitle(m));
      }
    }
    return titles;
  }, [llmProviders]);

  const configTitle = useCallback(
    (config: ImageGenerationConfigView): string =>
      titleByImageProviderId.get(config.image_provider_id) ?? config.model_name,
    [titleByImageProviderId]
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
    const modelKey = `${llmProvider.llm_provider_id}:${model.name}`;
    setLinkingModelKey(modelKey);
    try {
      await linkImageGenerationModel(
        llmProvider.llm_provider_id,
        model.name,
        !defaultConfig
      );
      toast.success(
        t("linkSuccess.message", { title: linkedModelTitle(model) })
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
      toast.success(
        t("disconnectSuccess.message", { title: disconnectProvider.title })
      );
      refetchAll();
    } catch (error) {
      console.error("Failed to disconnect image generation provider:", error);
      toast.error(
        error instanceof Error ? error.message : t("disconnectError.message")
      );
    } finally {
      setDisconnectProvider(null);
      setReplacementProviderId(null);
    }
  };

  const handleModalSuccess = () => {
    toast.success(t("configureSuccess.message"));
    setEditConfig(null);
    refetchConfigs();
  };

  // Compute replacement options when disconnecting an active provider
  const isDisconnectingDefault =
    disconnectProvider &&
    defaultConfig?.image_provider_id === disconnectProvider.image_provider_id;

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

  const handleDefaultChange = (value: string) => {
    if (value !== NO_DEFAULT_VALUE) {
      void handleSelect(value);
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
            <InputSingleSelect
              value={defaultConfig?.image_provider_id ?? NO_DEFAULT_VALUE}
              onValueChange={handleDefaultChange}
              placeholder={t("model.placeholder")}
              options={[...configGroups(configs, configTitle), noDefaultOption]}
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
              title={t("connectedModels.title")}
              sizePreset="main-content"
              variant="section"
            />
            <Section gap={2} height="fit" alignItems="stretch">
              {configs.map((config) => {
                const imageProviderId = config.image_provider_id;
                const legacyProvider = config.llm_provider_owned
                  ? legacyProviderById.get(imageProviderId)
                  : undefined;
                const title = configTitle(config);
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
                        : t("linkedModel.description", {
                            provider:
                              config.llm_provider_name ??
                              config.llm_provider_type,
                          })
                    }
                    ariaLabel={
                      config.llm_provider_owned
                        ? `image-gen-provider-${imageProviderId}`
                        : `image-gen-model-${config.llm_provider_id}-${config.model_name}`
                    }
                    isDefault={config.is_default}
                    disconnectModalOpen={
                      disconnectProvider?.image_provider_id === imageProviderId
                    }
                    onDisconnect={() =>
                      setDisconnectProvider({
                        image_provider_id: imageProviderId,
                        title,
                        llmProviderOwned: config.llm_provider_owned,
                      })
                    }
                    onEdit={
                      legacyProvider
                        ? () => handleEdit(legacyProvider)
                        : config.llm_provider_owned
                          ? undefined
                          : () => router.push(ADMIN_ROUTES.LLM_MODELS.path)
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
            title={t("availableModels.title")}
            description={t("availableModels.description")}
            sizePreset="main-content"
            variant="section"
          />
          <Tabs
            variant="pill"
            value={modelFilter}
            onValueChange={(value) =>
              setModelFilter(value === "all" ? "all" : "recommended")
            }
            gap={3}
          >
            <Tabs.List>
              <Tabs.Trigger value="recommended">
                {t("modelFilter.recommended")}
              </Tabs.Trigger>
              <Tabs.Trigger value="all">{t("modelFilter.all")}</Tabs.Trigger>
            </Tabs.List>
            <Tabs.Content value={modelFilter}>
              {availableGroups.length === 0 ? (
                <IllustrationContent
                  illustration={SvgEmpty}
                  title={t("noImageModels.title")}
                  description={t("noImageModels.description")}
                />
              ) : (
                <Section gap={8} height="fit" alignItems="stretch">
                  {availableGroups.map((llmProvider) => {
                    const providerName =
                      llmProvider.llm_provider_name ?? llmProvider.provider;
                    return (
                      <Section
                        key={`llm-${llmProvider.llm_provider_id}`}
                        gap={3}
                        height="fit"
                        alignItems="stretch"
                        justifyContent="start"
                      >
                        <Text font="main-ui-action" color="text-03">
                          {providerName}
                        </Text>
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
                                  title === model.name
                                    ? t("linkedModel.description", {
                                        provider: providerName,
                                      })
                                    : model.name
                                }
                                ariaLabel={`image-gen-model-${llmProvider.llm_provider_id}-${model.name}`}
                                disabled={linkingModelKey !== null}
                                onConnect={() =>
                                  void handleLink(llmProvider, model)
                                }
                              />
                            );
                          })}
                        </CardGrid>
                      </Section>
                    );
                  })}
                </Section>
              )}
            </Tabs.Content>
          </Tabs>
        </Section>
      )}

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
          onClose={() => {
            setDisconnectProvider(null);
            setReplacementProviderId(null);
          }}
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
