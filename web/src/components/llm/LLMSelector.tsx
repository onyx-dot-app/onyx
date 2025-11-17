import React, { useMemo } from "react";
import { getDisplayNameForModel } from "@/lib/hooks";
import {
  parseLlmDescriptor,
  modelSupportsImageInput,
  structureValue,
} from "@/lib/llm/utils";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import * as InputSelect from "@/refresh-components/inputs/InputSelect";
import { createIcon } from "@/components/icons/icons";

interface LLMSelectorProps {
  userSettings?: boolean;
  llmProviders: LLMProviderDescriptor[];
  currentLlm: string | null;
  onSelect: (value: string | null) => void;
  requiresImageGeneration?: boolean;
  excludePublicProviders?: boolean;
}

export const LLMSelector: React.FC<LLMSelectorProps> = ({
  userSettings,
  llmProviders,
  currentLlm,
  onSelect,
  requiresImageGeneration,
  excludePublicProviders = false,
}) => {
  const currentDescriptor = useMemo(
    () => (currentLlm ? parseLlmDescriptor(currentLlm) : null),
    [currentLlm]
  );

  const llmOptions = useMemo(() => {
    const seenDisplayNames = new Set<string>();
    const options: {
      name: string;
      value: string;
      icon: ReturnType<typeof getProviderIcon>;
      modelName: string;
      providerName: string;
      supportsImageInput: boolean;
    }[] = [];

    llmProviders.forEach((provider) => {
      provider.model_configurations.forEach((modelConfiguration) => {
        const displayName = getDisplayNameForModel(modelConfiguration.name);

        const matchesCurrentSelection =
          currentDescriptor?.modelName === modelConfiguration.name &&
          (currentDescriptor?.provider === provider.provider ||
            currentDescriptor?.name === provider.name);

        if (!modelConfiguration.is_visible && !matchesCurrentSelection) {
          return;
        }

        if (seenDisplayNames.has(displayName)) {
          return;
        }

        const supportsImageInput = modelSupportsImageInput(
          llmProviders,
          modelConfiguration.name,
          provider.name
        );

        const option = {
          name: displayName,
          value: structureValue(
            provider.name,
            provider.provider,
            modelConfiguration.name
          ),
          icon: getProviderIcon(provider.provider, modelConfiguration.name),
          modelName: modelConfiguration.name,
          providerName: provider.name,
          supportsImageInput,
        };

        if (requiresImageGeneration && !supportsImageInput) {
          return;
        }

        seenDisplayNames.add(displayName);
        options.push(option);
      });
    });

    return options;
  }, [
    llmProviders,
    currentDescriptor?.modelName,
    currentDescriptor?.provider,
    currentDescriptor?.name,
    requiresImageGeneration,
  ]);

  const defaultProvider = llmProviders.find(
    (llmProvider) => llmProvider.is_default_provider
  );

  const defaultModelName = defaultProvider?.default_model_name;
  const defaultModelDisplayName = defaultModelName
    ? getDisplayNameForModel(defaultModelName)
    : null;
  const defaultLabel = userSettings ? "System Default" : "User Default";

  return (
    <InputSelect.Root
      value={currentLlm ? currentLlm : "default"}
      onValueChange={(value) => onSelect(value === "default" ? null : value)}
      placeholder={defaultLabel}
    >
      {!excludePublicProviders && (
        <InputSelect.Item
          value="default"
          description={
            userSettings && defaultModelDisplayName
              ? `(${defaultModelDisplayName})`
              : undefined
          }
        >
          {defaultLabel}
        </InputSelect.Item>
      )}
      {llmOptions.map((option) => (
        <InputSelect.Item
          key={option.value}
          value={option.value}
          icon={createIcon(option.icon)}
        >
          {option.name}
        </InputSelect.Item>
      ))}
    </InputSelect.Root>
  );
};
