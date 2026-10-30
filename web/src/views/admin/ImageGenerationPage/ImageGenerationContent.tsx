"use client";

import { PageLoader } from "@opal/loaders";
import { useState, useMemo, useEffect } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useCreateModal } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
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
import { ConfirmationModalLayout } from "@opal/layouts";
import {
  InputSingleSelect,
  InputSwitch,
  type SelectDivider,
} from "@opal/components";
import { Button, MessageCard, Text } from "@opal/components";
import { Content, IllustrationContent, toast } from "@opal/layouts";
import { SvgEmpty } from "@opal/illustrations";
import { SvgSlash, SvgUnplug } from "@opal/icons";
import { markdown } from "@opal/utils";
import { getImageGenForm } from "@/views/admin/ImageGenerationPage/forms";
import ProviderCard from "@/sections/admin/ProviderCard";
import { getModelIcon } from "@/lib/languageModels/utils";

const NO_DEFAULT_VALUE = "__none__";

interface DisconnectTarget {
  image_provider_id: string;
  title: string;
  llmProviderOwned: boolean;
}

function linkedModelTitle(model: ImageGenerationProviderModel): string {
  return model.display_name || model.name;
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
  const [showRecommendedOnly, setShowRecommendedOnly] = useState(true);
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
  const legacyGroups = useMemo(() => {
    const ownedIds = new Set(
      configs
        .filter((c) => c.llm_provider_owned)
        .map((c) => c.image_provider_id)
    );
    return IMAGE_PROVIDER_GROUPS.map((group) => ({
      ...group,
      providers: group.providers.filter((p) =>
        ownedIds.has(p.image_provider_id)
      ),
    })).filter((g) => g.providers.length > 0);
  }, [configs]);

  const linkedGroups = useMemo(() => {
    return llmProviders
      .map((llmProvider) => ({
        ...llmProvider,
        models: llmProvider.models.filter(
          (m) => !showRecommendedOnly || m.is_recommended || m.image_provider_id
        ),
      }))
      .filter((group) => group.models.length > 0);
  }, [llmProviders, showRecommendedOnly]);

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

  const configTitle = (config: ImageGenerationConfigView): string =>
    titleByImageProviderId.get(config.image_provider_id) ?? config.model_name;

  const connectedDeprecatedProviders = useMemo(() => {
    return IMAGE_PROVIDER_GROUPS.flatMap((group) => group.providers).filter(
      (p) => p.deprecated && connectedProviderIds.has(p.image_provider_id)
    );
  }, [connectedProviderIds]);

  const defaultConfig = useMemo(() => {
    return configs.find((c) => c.is_default);
  }, [configs]);

  const getStatus = (
    imageProviderId: string | null
  ): "disconnected" | "connected" | "selected" => {
    if (!imageProviderId) return "disconnected";
    if (defaultConfig?.image_provider_id === imageProviderId) return "selected";
    if (connectedProviderIds.has(imageProviderId)) return "connected";
    return "disconnected";
  };

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

  // Connected replacement models grouped by LLM provider, without the model being disconnected
  const replacementGroups = useMemo(() => {
    if (!disconnectProvider) return [];
    const groups = new Map<
      string,
      { name: string; configs: ImageGenerationConfigView[] }
    >();
    for (const config of configs) {
      if (config.image_provider_id === disconnectProvider.image_provider_id)
        continue;
      const name = config.llm_provider_name ?? config.llm_provider_type;
      const group = groups.get(name) ?? { name, configs: [] };
      group.configs.push(config);
      groups.set(name, group);
    }
    return Array.from(groups.values());
  }, [disconnectProvider, configs]);

  const needsReplacement = !!isDisconnectingDefault;
  const hasReplacements = replacementGroups.length > 0;

  // Auto-select first replacement when modal opens
  useEffect(() => {
    if (needsReplacement && !replacementProviderId && hasReplacements) {
      const firstGroup = replacementGroups[0];
      const firstModel = firstGroup?.configs[0];
      if (firstModel) setReplacementProviderId(firstModel.image_provider_id);
    }
  }, [disconnectProvider]);

  if (configError) {
    return <div className="text-error">{t("loadError.message")}</div>;
  }

  if (configsLoading || llmProvidersLoading) {
    return <PageLoader />;
  }

  return (
    <>
      <div className="flex flex-col gap-4">
        <Content
          title={t("model.title")}
          description={t("model.description")}
          sizePreset="main-content"
          variant="section"
        />

        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          gap={0.75}
        >
          <Text font="secondary-body" color="text-03">
            {t("recommendedOnly.label")}
          </Text>
          <InputSwitch
            aria-label={t("recommendedOnly.label")}
            checked={showRecommendedOnly}
            onCheckedChange={setShowRecommendedOnly}
          />
        </Section>

        {connectedProviderIds.size === 0 && (
          <MessageCard variant="info" title={t("emptyState.title")} />
        )}

        {llmProvidersError && (
          <MessageCard variant="error" title={t("loadError.message")} />
        )}

        {!llmProvidersError &&
          linkedGroups.length === 0 &&
          legacyGroups.length === 0 && (
            <IllustrationContent
              illustration={SvgEmpty}
              title={t("noImageModels.title")}
              description={t("noImageModels.description")}
            />
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

        {linkedGroups.map((llmProvider) => (
          <Section
            key={`llm-${llmProvider.llm_provider_id}`}
            alignItems="stretch"
            gap={0.5}
          >
            <Content
              title={llmProvider.llm_provider_name ?? llmProvider.provider}
              sizePreset="secondary"
              variant="body"
            />
            {llmProvider.models.map((model) => {
              const modelKey = `${llmProvider.llm_provider_id}:${model.name}`;
              const imageProviderId = model.image_provider_id;
              const title = linkedModelTitle(model);
              return (
                <ProviderCard
                  key={modelKey}
                  icon={getModelIcon(llmProvider.provider, model.name)}
                  title={title}
                  description={
                    title === model.name
                      ? t("linkedModel.description", {
                          provider:
                            llmProvider.llm_provider_name ??
                            llmProvider.provider,
                        })
                      : model.name
                  }
                  status={getStatus(imageProviderId)}
                  aria-label={`image-gen-model-${llmProvider.llm_provider_id}-${model.name}`}
                  onConnect={
                    linkingModelKey !== null
                      ? undefined
                      : () => void handleLink(llmProvider, model)
                  }
                  onSelect={() => handleSelect(imageProviderId)}
                  onDeselect={() => handleDeselect(imageProviderId)}
                  onDisconnect={
                    imageProviderId
                      ? () =>
                          setDisconnectProvider({
                            image_provider_id: imageProviderId,
                            title,
                            llmProviderOwned: false,
                          })
                      : undefined
                  }
                  disconnectModalOpen={
                    !!imageProviderId &&
                    disconnectProvider?.image_provider_id === imageProviderId
                  }
                />
              );
            })}
          </Section>
        ))}

        {legacyGroups.map((group) => (
          <Section key={group.name} alignItems="stretch" gap={0.5}>
            <Content title={group.name} sizePreset="secondary" variant="body" />
            {group.providers.map((provider) => (
              <ProviderCard
                key={provider.image_provider_id}
                icon={getModelIcon(provider.provider_name)}
                title={provider.title}
                description={t(provider.descriptionKey)}
                status={getStatus(provider.image_provider_id)}
                aria-label={`image-gen-provider-${provider.image_provider_id}`}
                onSelect={() => handleSelect(provider.image_provider_id)}
                onDeselect={() => handleDeselect(provider.image_provider_id)}
                onEdit={() => handleEdit(provider)}
                onDisconnect={() =>
                  setDisconnectProvider({
                    image_provider_id: provider.image_provider_id,
                    title: provider.title,
                    llmProviderOwned: true,
                  })
                }
                disconnectModalOpen={
                  disconnectProvider?.image_provider_id ===
                  provider.image_provider_id
                }
              />
            ))}
          </Section>
        ))}
      </div>

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
                    options={[
                      ...replacementGroups.map(
                        (group): SelectDivider => ({
                          title: group.name,
                          options: group.configs.map((c) => ({
                            value: c.image_provider_id,
                            title: configTitle(c),
                            icon: getModelIcon(
                              c.llm_provider_type,
                              c.model_name
                            ),
                          })),
                        })
                      ),
                      {
                        value: NO_DEFAULT_VALUE,
                        title: t("disconnectModal.noDefaultOption.label"),
                        description: t(
                          "disconnectModal.noDefaultOption.description"
                        ),
                        icon: SvgSlash,
                      },
                    ]}
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
