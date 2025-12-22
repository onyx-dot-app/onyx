"use client";

import { useState, useMemo } from "react";
import useSWR from "swr";
import Text from "@/refresh-components/texts/Text";
import { Select } from "@/refresh-components/card";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { usePopup } from "@/components/admin/connectors/Popup";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  LLMProviderView,
  WellKnownLLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";
import { IMAGE_PROVIDER_GROUPS, ImageProvider } from "./constants";
import ImageGenerationConnectionModal from "./ImageGenerationConnectionModal";
import {
  ImageGenerationConfigView,
  setDefaultImageGenerationConfig,
} from "@/lib/configuration/imageConfigurationService";

export default function ImageGenerationContent() {
  const { popup, setPopup } = usePopup();

  const {
    data: llmProviders = [],
    error: llmError,
    mutate: refetchProviders,
  } = useSWR<LLMProviderView[]>(
    "/api/admin/llm/provider",
    errorHandlingFetcher
  );

  const {
    data: configs = [],
    error: configError,
    mutate: refetchConfigs,
  } = useSWR<ImageGenerationConfigView[]>(
    "/api/admin/image-generation/config",
    errorHandlingFetcher
  );

  const { data: llmDescriptors = [] } = useSWR<
    WellKnownLLMProviderDescriptor[]
  >("/api/admin/llm/built-in/options", errorHandlingFetcher);

  const getLLMDescriptor = (imageProvider: ImageProvider) => {
    const llmProviderName = imageProvider.provider_name;
    return llmDescriptors.find((d) => d.name === llmProviderName);
  };

  const modal = useCreateModal();
  const [activeProvider, setActiveProvider] = useState<ImageProvider | null>(
    null
  );
  const [editConfig, setEditConfig] =
    useState<ImageGenerationConfigView | null>(null);

  const connectedProviderIds = useMemo(() => {
    return new Set(configs.map((c) => c.model_name));
  }, [configs]);

  const defaultConfig = useMemo(() => {
    return configs.find((c) => c.is_default);
  }, [configs]);

  const getStatus = (
    provider: ImageProvider
  ): "disconnected" | "connected" | "selected" => {
    if (defaultConfig?.model_name === provider.id) return "selected";
    if (connectedProviderIds.has(provider.id)) return "connected";
    return "disconnected";
  };

  const handleConnect = (provider: ImageProvider) => {
    setEditConfig(null);
    setActiveProvider(provider);
    modal.toggle(true);
  };

  const handleSelect = async (provider: ImageProvider) => {
    const config = configs.find((c) => c.model_name === provider.id);
    if (config) {
      try {
        await setDefaultImageGenerationConfig(config.id);
        setPopup({
          message: `${provider.title} set as default`,
          type: "success",
        });
        refetchConfigs();
      } catch (error) {
        setPopup({
          message:
            error instanceof Error ? error.message : "Failed to set default",
          type: "error",
        });
      }
    }
  };

  const handleDeselect = () => {
    refetchConfigs();
  };

  const handleEdit = (provider: ImageProvider) => {
    const config = configs.find((c) => c.model_name === provider.id);
    setEditConfig(config || null);
    setActiveProvider(provider);
    modal.toggle(true);
  };

  const handleModalSuccess = () => {
    setPopup({ message: "Provider configured successfully", type: "success" });
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

  return (
    <>
      {popup}
      <div className="flex flex-col gap-6">
        {/* Section Header */}
        <div className="flex flex-col gap-0.5">
          <Text mainContentEmphasis text05>
            Image Generation Model
          </Text>
          <Text secondaryBody text03>
            Select a model to generate images in chat.
          </Text>
        </div>

        {/* Provider Groups */}
        {IMAGE_PROVIDER_GROUPS.map((group) => (
          <div key={group.name} className="flex flex-col gap-2">
            <Text secondaryBody text03>
              {group.name}
            </Text>
            <div className="flex flex-col gap-2">
              {group.providers.map((provider) => (
                <Select
                  key={provider.id}
                  icon={provider.icon}
                  title={provider.title}
                  description={provider.description}
                  status={getStatus(provider)}
                  onConnect={() => handleConnect(provider)}
                  onSelect={() => handleSelect(provider)}
                  onDeselect={handleDeselect}
                  onEdit={() => handleEdit(provider)}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      {activeProvider && (
        <modal.Provider>
          <ImageGenerationConnectionModal
            modal={modal}
            imageProvider={activeProvider}
            llmDescriptor={getLLMDescriptor(activeProvider)}
            existingProviders={llmProviders}
            existingConfig={editConfig || undefined}
            onSuccess={handleModalSuccess}
            setPopup={setPopup}
          />
        </modal.Provider>
      )}
    </>
  );
}
