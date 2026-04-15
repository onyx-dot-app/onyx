"use client";

import { useState, useMemo, useEffect } from "react";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import { Section } from "@/layouts/general-layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { LLMProviderResponse, LLMProviderView } from "@/interfaces/llm";
import {
  IMAGE_PROVIDER_GROUPS,
  ImageProvider,
} from "@/refresh-pages/admin/ImageGenerationPage/constants";
import {
  ImageGenerationConfigView,
  setDefaultImageGenerationConfig,
  unsetDefaultImageGenerationConfig,
  deleteImageGenerationConfig,
} from "@/refresh-pages/admin/ImageGenerationPage/svc";
import ModelIcon from "@/app/admin/configuration/llm/ModelIcon";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Button, MessageCard, SelectCard, Text } from "@opal/components";
import { Content, Card } from "@opal/layouts";
import { Hoverable } from "@opal/core";
import {
  SvgArrowExchange,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgSettings,
  SvgSlash,
  SvgUnplug,
} from "@opal/icons";
import { markdown } from "@opal/utils";
import { getImageGenForm } from "@/refresh-pages/admin/ImageGenerationPage/forms";

const NO_DEFAULT_VALUE = "__none__";

const STATUS_TO_STATE = {
  disconnected: "empty",
  connected: "filled",
  selected: "selected",
} as const;

export default function ImageGenerationContent() {
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
        toast.success(`${provider.title} set as default`);
        refetchConfigs();
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : "Failed to set default"
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
        toast.success(`${provider.title} deselected`);
        refetchConfigs();
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : "Failed to deselect"
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
      toast.success(`${disconnectProvider.title} disconnected`);
      refetchConfigs();
      refetchProviders();
    } catch (error) {
      console.error("Failed to disconnect image generation provider:", error);
      toast.error(
        error instanceof Error ? error.message : "Failed to disconnect"
      );
    } finally {
      setDisconnectProvider(null);
      setReplacementProviderId(null);
    }
  };

  const handleModalSuccess = () => {
    toast.success("Provider configured successfully");
    setEditConfig(null);
    refetchConfigs();
    refetchProviders();
  };

  if (llmError || configError) {
    return (
      <div className="text-error">
        Failed to load configuration. Please refresh the page.
      </div>
    );
  }

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

  return (
    <>
      <div className="flex flex-col gap-4">
        <Content
          title="Image Generation Model"
          description="Select a model to generate images in chat."
          sizePreset="main-content"
          variant="section"
        />

        {connectedProviderIds.size === 0 && (
          <MessageCard
            variant="info"
            title="Connect an image generation model to use in chat."
          />
        )}

        {/* Provider Groups */}
        {IMAGE_PROVIDER_GROUPS.map((group) => (
          <div key={group.name} className="flex flex-col gap-2">
            <Content title={group.name} sizePreset="secondary" variant="body" />
            {group.providers.map((provider) => {
              const status = getStatus(provider);
              const isDisconnected = status === "disconnected";
              const isConnected = status === "connected";
              const isSelected = status === "selected";

              return (
                <Hoverable.Root
                  key={provider.image_provider_id}
                  group="image-gen/ProviderCard"
                >
                  <SelectCard
                    state={STATUS_TO_STATE[status]}
                    padding="sm"
                    rounding="lg"
                    aria-label={`image-gen-provider-${provider.image_provider_id}`}
                    onClick={
                      isDisconnected
                        ? () => handleConnect(provider)
                        : isSelected
                          ? () => handleDeselect(provider)
                          : undefined
                    }
                  >
                    <Card.Header
                      sizePreset="main-ui"
                      variant="section"
                      icon={() => (
                        <ModelIcon
                          provider={provider.provider_name}
                          size={16}
                        />
                      )}
                      title={provider.title}
                      description={provider.description}
                      rightChildren={
                        isDisconnected ? (
                          <Button
                            prominence="tertiary"
                            rightIcon={SvgArrowExchange}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleConnect(provider);
                            }}
                          >
                            Connect
                          </Button>
                        ) : isConnected ? (
                          <Button
                            prominence="tertiary"
                            rightIcon={SvgArrowRightCircle}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleSelect(provider);
                            }}
                          >
                            Set as Default
                          </Button>
                        ) : isSelected ? (
                          <div className="p-2">
                            <Content
                              title="Current Default"
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
                            <Hoverable.Item group="image-gen/ProviderCard">
                              <Button
                                icon={SvgUnplug}
                                tooltip="Disconnect"
                                aria-label={`Disconnect ${provider.title}`}
                                prominence="tertiary"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setDisconnectProvider(provider);
                                }}
                                size="md"
                              />
                            </Hoverable.Item>
                            <Button
                              icon={SvgSettings}
                              tooltip="Edit"
                              aria-label={`Edit ${provider.title}`}
                              prominence="tertiary"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleEdit(provider);
                              }}
                              size="md"
                            />
                          </div>
                        ) : undefined
                      }
                    />
                  </SelectCard>
                </Hoverable.Root>
              );
            })}
          </div>
        ))}
      </div>

      {disconnectProvider && (
        <ConfirmationModalLayout
          icon={SvgUnplug}
          title={markdown(`Disconnect *${disconnectProvider.title}*`)}
          description="This will remove the stored credentials for this provider."
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
              Disconnect
            </Button>
          }
        >
          {needsReplacement ? (
            hasReplacements ? (
              <Section alignItems="start">
                <Text as="p" color="text-03">
                  {markdown(
                    `**${disconnectProvider.title}** is currently the default image generation model. Session history will be preserved.`
                  )}
                </Text>
                <Section alignItems="start" gap={0.25}>
                  <Text as="p" color="text-04">
                    Set New Default
                  </Text>
                  <InputSelect
                    value={replacementProviderId ?? undefined}
                    onValueChange={(v) => setReplacementProviderId(v)}
                  >
                    <InputSelect.Trigger placeholder="Select a replacement model" />
                    <InputSelect.Content>
                      {replacementGroups.map((group) => (
                        <InputSelect.Group key={group.name}>
                          <InputSelect.Label>{group.name}</InputSelect.Label>
                          {group.providers.map((p) => (
                            <InputSelect.Item
                              key={p.image_provider_id}
                              value={p.image_provider_id}
                              icon={() => (
                                <ModelIcon
                                  provider={p.provider_name}
                                  size={16}
                                />
                              )}
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
                          <b>No Default</b>
                          <span className="text-text-03">
                            {" "}
                            (Disable Image Generation)
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
                    `**${disconnectProvider.title}** is currently the default image generation model.`
                  )}
                </Text>
                <Text as="p" color="text-03">
                  Connect another provider to continue using image generation.
                </Text>
              </>
            )
          ) : (
            <>
              <Text as="p" color="text-03">
                {markdown(
                  `**${disconnectProvider.title}** models will no longer be used to generate images.`
                )}
              </Text>
              <Text as="p" color="text-03">
                Session history will be preserved.
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
