"use client";

import { useState, useMemo, useEffect } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useCreateModal } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  LLMProviderResponse,
  LLMProviderView,
} from "@/lib/languageModels/types";
import {
  IMAGE_PROVIDER_GROUPS,
  ImageProvider,
} from "@/views/admin/ImageGenerationPage/constants";
import {
  ImageGenerationConfigView,
  setDefaultImageGenerationConfig,
  unsetDefaultImageGenerationConfig,
  deleteImageGenerationConfig,
} from "@/views/admin/ImageGenerationPage/svc";
import { ConfirmationModalLayout } from "@opal/layouts";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Button, MessageCard, Text } from "@opal/components";
import { Content, toast } from "@opal/layouts";
import { SvgSlash, SvgUnplug } from "@opal/icons";
import { markdown } from "@opal/utils";
import { getImageGenForm } from "@/views/admin/ImageGenerationPage/forms";
import ProviderCard from "@/sections/admin/ProviderCard";
import { getModelIcon } from "@/lib/languageModels";

const NO_DEFAULT_VALUE = "__none__";

export default function ImageGenerationContent() {
  const t = useTranslations("admin.imageGeneration");
  const {
    data: llmProviderResponse,
    error: llmError,
    mutate: refetchProviders,
  } = useSWR<LLMProviderResponse<LLMProviderView>>(
    SWR_KEYS.llmProvidersWithImageGen,
    errorHandlingFetcher
  );
  const llmProviders = llmProviderResponse?.providers ?? [];

  const {
    data: configs = [],
    error: configError,
    mutate: refetchConfigs,
  } = useSWR<ImageGenerationConfigView[]>(
    SWR_KEYS.imageGenConfig,
    errorHandlingFetcher
  );

  const modal = useCreateModal();
  const [activeProvider, setActiveProvider] = useState<ImageProvider | null>(
    null
  );
  const [editConfig, setEditConfig] =
    useState<ImageGenerationConfigView | null>(null);
  const [disconnectProvider, setDisconnectProvider] =
    useState<ImageProvider | null>(null);
  const [replacementProviderId, setReplacementProviderId] = useState<
    string | null
  >(null);

  const connectedProviderIds = useMemo(() => {
    return new Set(configs.map((c) => c.image_provider_id));
  }, [configs]);

  // Deprecated models stay visible only for admins who already connected them,
  // so they can still disconnect or switch away.
  const visibleGroups = useMemo(() => {
    return IMAGE_PROVIDER_GROUPS.map((group) => ({
      ...group,
      providers: group.providers.filter(
        (p) => !p.deprecated || connectedProviderIds.has(p.image_provider_id)
      ),
    })).filter((g) => g.providers.length > 0);
  }, [connectedProviderIds]);

  const defaultConfig = useMemo(() => {
    return configs.find((c) => c.is_default);
  }, [configs]);

  const getStatus = (
    provider: ImageProvider
  ): "disconnected" | "connected" | "selected" => {
    if (defaultConfig?.image_provider_id === provider.image_provider_id)
      return "selected";
    if (connectedProviderIds.has(provider.image_provider_id))
      return "connected";
    return "disconnected";
  };

  const handleConnect = (provider: ImageProvider) => {
    setEditConfig(null);
    setActiveProvider(provider);
    modal.toggle(true);
  };

  const handleSelect = async (provider: ImageProvider) => {
    const config = configs.find(
      (c) => c.image_provider_id === provider.image_provider_id
    );
    if (config) {
      try {
        await setDefaultImageGenerationConfig(config.image_provider_id);
        toast.success(
          t("setDefaultSuccess.message", { title: provider.title })
        );
        refetchConfigs();
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : t("setDefaultError.message")
        );
      }
    }
  };

  const handleDeselect = async (provider: ImageProvider) => {
    const config = configs.find(
      (c) => c.image_provider_id === provider.image_provider_id
    );
    if (config) {
      try {
        await unsetDefaultImageGenerationConfig(config.image_provider_id);
        toast.success(t("deselectSuccess.message", { title: provider.title }));
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
      refetchConfigs();
      refetchProviders();
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
    refetchProviders();
  };

  // Compute replacement options when disconnecting an active provider
  const isDisconnectingDefault =
    disconnectProvider &&
    defaultConfig?.image_provider_id === disconnectProvider.image_provider_id;

  // Group connected replacement models by provider (excluding the model being disconnected)
  const replacementGroups = useMemo(() => {
    if (!disconnectProvider) return [];
    return IMAGE_PROVIDER_GROUPS.map((group) => ({
      ...group,
      providers: group.providers.filter(
        (p) =>
          p.image_provider_id !== disconnectProvider.image_provider_id &&
          connectedProviderIds.has(p.image_provider_id)
      ),
    })).filter((g) => g.providers.length > 0);
  }, [disconnectProvider, connectedProviderIds]);

  const needsReplacement = !!isDisconnectingDefault;
  const hasReplacements = replacementGroups.length > 0;

  // Auto-select first replacement when modal opens
  useEffect(() => {
    if (needsReplacement && !replacementProviderId && hasReplacements) {
      const firstGroup = replacementGroups[0];
      const firstModel = firstGroup?.providers[0];
      if (firstModel) setReplacementProviderId(firstModel.image_provider_id);
    }
  }, [disconnectProvider]); // eslint-disable-line react-hooks/exhaustive-deps

  if (llmError || configError) {
    return <div className="text-error">{t("loadError.message")}</div>;
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

        {connectedProviderIds.size === 0 && (
          <MessageCard variant="info" title={t("emptyState.title")} />
        )}

        {/* Provider Groups */}
        {visibleGroups.map((group) => (
          <div key={group.name} className="flex flex-col gap-2">
            <Content title={group.name} sizePreset="secondary" variant="body" />
            {group.providers.map((provider) => {
              const status = getStatus(provider);
              const isDisconnected = status === "disconnected";
              const isConnected = status === "connected";
              const isSelected = status === "selected";

              return (
                <ProviderCard
                  key={provider.image_provider_id}
                  icon={getModelIcon(provider.provider_name)}
                  title={provider.title}
                  description={t(provider.descriptionKey)}
                  status={status}
                  aria-label={`image-gen-provider-${provider.image_provider_id}`}
                  onConnect={() => handleConnect(provider)}
                  onSelect={() => handleSelect(provider)}
                  onDeselect={() => handleDeselect(provider)}
                  onEdit={() => handleEdit(provider)}
                  onDisconnect={() => setDisconnectProvider(provider)}
                  disconnectModalOpen={
                    disconnectProvider?.image_provider_id ===
                    provider.image_provider_id
                  }
                />
              );
            })}
          </div>
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
          description={t("disconnectModal.header.description")}
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
                  <InputSelect
                    value={replacementProviderId ?? undefined}
                    onValueChange={(v) => setReplacementProviderId(v)}
                  >
                    <InputSelect.Trigger
                      placeholder={t("disconnectModal.replacement.placeholder")}
                    />
                    <InputSelect.Content>
                      {replacementGroups.map((group) => (
                        <InputSelect.Group key={group.name}>
                          <InputSelect.Label>{group.name}</InputSelect.Label>
                          {group.providers.map((p) => (
                            <InputSelect.Item
                              key={p.image_provider_id}
                              value={p.image_provider_id}
                              icon={getModelIcon(p.provider_name)}
                            >
                              {p.title}
                            </InputSelect.Item>
                          ))}
                        </InputSelect.Group>
                      ))}
                      <InputSelect.Separator />
                      <InputSelect.Item
                        value={NO_DEFAULT_VALUE}
                        icon={SvgSlash}
                      >
                        <span>
                          <b>{t("disconnectModal.noDefaultOption.label")}</b>
                          <span className="text-text-03">
                            {" "}
                            {t("disconnectModal.noDefaultOption.description")}
                          </span>
                        </span>
                      </InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelect>
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
            existingProviders: llmProviders,
            existingConfig: editConfig || undefined,
            onSuccess: handleModalSuccess,
          })}
        </modal.Provider>
      )}
    </>
  );
}
