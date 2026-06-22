"use client";

import { useMemo } from "react";
import { parseLlmDescriptor, structureValue } from "@/lib/languageModels/utils";
import {
  DefaultModel,
  LLMProviderDescriptor,
} from "@/lib/languageModels/types";
import { getModelIcon, getProvider } from "@/lib/languageModels";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { createIcon } from "@/components/icons/icons";

interface LLMOption {
  name: string;
  value: string;
  icon: ReturnType<typeof getModelIcon>;
  modelName: string;
  providerId: number;
  providerName: string;
  provider: string;
  supplierId: string | null;
  supplierDisplayName: string | null;
  supportsImageInput: boolean;
  vendor: string | null;
}

export interface LLMSelectorProps {
  name?: string;
  userSettings?: boolean;
  llmProviders: LLMProviderDescriptor[];
  defaultText?: DefaultModel | null;
  currentLlm: string | null;
  onSelect: (value: string | null) => void;
  requiresImageGeneration?: boolean;
  excludePublicProviders?: boolean;
}

export default function LLMSelector({
  name,
  userSettings,
  llmProviders,
  defaultText,
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

        const key = `${provider.id}:${modelConfiguration.name}`;
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

        // For nameless providers, fall back to the provider ID so the
        // structured value is always unique and non-empty.
        const providerLabel =
          provider.supplier_display_name ??
          provider.name ??
          getProvider(provider.provider).productName;
        const option: LLMOption = {
          name: displayName,
          value: structureValue(
            provider.name ?? String(provider.id),
            provider.provider,
            modelConfiguration.name
          ),
          icon: getModelIcon(provider.provider, modelConfiguration.name),
          modelName: modelConfiguration.name,
          providerId: provider.id,
          providerName: providerLabel,
          provider: provider.provider,
          supplierId: provider.supplier_id ?? null,
          supplierDisplayName: provider.supplier_display_name ?? null,
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

  // Group options by backend supplier when available; otherwise keep the
  // configured provider instance grouping for custom/admin providers.
  const groupedOptions = useMemo(() => {
    const groups = new Map<
      string,
      { providerId: number; displayName: string; options: LLMOption[] }
    >();

    llmOptions.forEach((option) => {
      const groupKey = option.supplierId
        ? `supplier:${option.supplierId}`
        : `provider:${option.providerId}`;
      if (!groups.has(groupKey)) {
        groups.set(groupKey, {
          providerId: option.providerId,
          displayName: option.providerName,
          options: [],
        });
      }
      groups.get(groupKey)!.options.push(option);
    });

    // Sort groups alphabetically by display name
    const sortedGroupKeys = Array.from(groups.keys()).sort((a, b) =>
      groups.get(a)!.displayName.localeCompare(groups.get(b)!.displayName)
    );

    return sortedGroupKeys.map((groupKey) => {
      const group = groups.get(groupKey)!;
      return {
        providerId: group.providerId,
        displayName: group.displayName,
        options: group.options,
      };
    });
  }, [llmOptions]);

  const defaultProvider = defaultText
    ? llmProviders.find((p) => p.id === defaultText.provider_id)
    : undefined;

  const defaultModelName = defaultText?.model_name;
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
      <InputSelect.Trigger id={name} name={name} placeholder={defaultLabel} />

      <InputSelect.Content>
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
              <InputSelect.Group key={group.providerId}>
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
