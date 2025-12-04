import { useMemo } from "react";
import {
  parseLlmDescriptor,
  modelSupportsImageInput,
  structureValue,
} from "@/lib/llm/utils";
import {
  LLMProviderDescriptor,
  ModelConfiguration,
} from "@/app/admin/configuration/llm/interfaces";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { createIcon } from "@/components/icons/icons";

interface LLMOption {
  name: string;
  value: string;
  icon: ReturnType<typeof getProviderIcon>;
  modelName: string;
  providerName: string;
  provider: string;
  providerDisplayName: string;
  supportsImageInput: boolean;
  vendor: string | null;
}

export interface LLMSelectorProps {
  userSettings?: boolean;
  llmProviders: LLMProviderDescriptor[];
  currentLlm: string | null;
  onSelect: (value: string | null) => void;
  requiresImageGeneration?: boolean;
  excludePublicProviders?: boolean;
}

export default function LLMSelector({
  userSettings,
  llmProviders,
  currentLlm,
  onSelect,
  requiresImageGeneration,
  excludePublicProviders = false,
}: LLMSelectorProps) {
  const currentDescriptor = useMemo(
    () => (currentLlm ? parseLlmDescriptor(currentLlm) : null),
    [currentLlm]
  );

  const llmOptions = useMemo(() => {
    const seenKeys = new Set<string>();
    const options: LLMOption[] = [];

    llmProviders.forEach((provider) => {
      provider.model_configurations.forEach((modelConfiguration) => {
        // Use the display name if it is available, otherwise use the model name
        const displayName =
          modelConfiguration.display_name || modelConfiguration.name;

        const matchesCurrentSelection =
          currentDescriptor?.modelName === modelConfiguration.name &&
          (currentDescriptor?.provider === provider.provider ||
            currentDescriptor?.name === provider.name);

        if (!modelConfiguration.is_visible && !matchesCurrentSelection) {
          return;
        }

        const key = `${provider.provider}:${modelConfiguration.name}`;
        if (seenKeys.has(key)) {
          return; // Skip exact duplicate
        }
        seenKeys.add(key);

        const supportsImageInput =
          modelConfiguration.supports_image_input || false;

        // If the model does not support image input and we require image generation, skip it
        if (requiresImageGeneration && !supportsImageInput) {
          return;
        }

        const option: LLMOption = {
          name: displayName,
          value: structureValue(
            provider.name,
            provider.provider,
            modelConfiguration.name
          ),
          icon: getProviderIcon(provider.provider, modelConfiguration.name),
          modelName: modelConfiguration.name,
          providerName: provider.name,
          provider: provider.provider,
          providerDisplayName:
            provider.provider_display_name || provider.provider,
          supportsImageInput,
          vendor: modelConfiguration.vendor || null,
        };

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

  // Group options by provider using backend-provided display names
  const groupedOptions = useMemo(() => {
    const groups = new Map<
      string,
      { displayName: string; options: LLMOption[] }
    >();

    llmOptions.forEach((option) => {
      const provider = option.provider.toLowerCase();
      if (!groups.has(provider)) {
        groups.set(provider, {
          displayName: option.providerDisplayName,
          options: [],
        });
      }
      groups.get(provider)!.options.push(option);
    });

    // Sort groups alphabetically by display name
    const sortedProviders = Array.from(groups.keys()).sort((a, b) =>
      groups.get(a)!.displayName.localeCompare(groups.get(b)!.displayName)
    );

    return sortedProviders.map((provider) => {
      const group = groups.get(provider)!;
      return {
        provider,
        displayName: group.displayName,
        options: group.options,
      };
    });
  }, [llmOptions]);

  const defaultProvider = llmProviders.find(
    (llmProvider) => llmProvider.is_default_provider
  );

  const defaultModelName = defaultProvider?.default_model_name;
  const defaultModelConfig = defaultProvider?.model_configurations.find(
    (m) => m.name === defaultModelName
  );
  const defaultModelDisplayName = defaultModelConfig
    ? defaultModelConfig.display_name || defaultModelConfig.name
    : defaultModelName || null;
  const defaultLabel = userSettings ? "System Default" : "User Default";

  // Determine if we should show grouped view (only if we have multiple vendors)
  const showGrouped = groupedOptions.length > 1;

  return (
    <InputSelect
      value={currentLlm ? currentLlm : "default"}
      onValueChange={(value) => onSelect(value === "default" ? null : value)}
    >
      <InputSelect.Trigger placeholder={defaultLabel} />

      <InputSelect.Content className="min-w-[280px]">
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
        {showGrouped
          ? groupedOptions.map((group) => (
              <InputSelect.Group key={group.provider}>
                <InputSelect.Label>{group.displayName}</InputSelect.Label>
                {group.options.map((option) => (
                  <InputSelect.Item
                    key={option.value}
                    value={option.value}
                    icon={createIcon(option.icon)}
                  >
                    {option.name}
                  </InputSelect.Item>
                ))}
              </InputSelect.Group>
            ))
          : llmOptions.map((option) => (
              <InputSelect.Item
                key={option.value}
                value={option.value}
                icon={createIcon(option.icon)}
              >
                {option.name}
              </InputSelect.Item>
            ))}
      </InputSelect.Content>
    </InputSelect>
  );
}
