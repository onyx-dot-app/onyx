import React, { useMemo } from "react";
import { getDisplayNameForModel } from "@/lib/hooks";
import {
  parseLlmDescriptor,
  modelSupportsImageInput,
  structureValue,
} from "@/lib/llm/utils";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface LLMSelectorProps {
  userSettings?: boolean;
  llmProviders: LLMProviderDescriptor[];
  currentLlm: string | null;
  onSelect: (value: string | null) => void;
  requiresImageGeneration?: boolean;
}

export const LLMSelector: React.FC<LLMSelectorProps> = ({
  userSettings,
  llmProviders,
  currentLlm,
  onSelect,
  requiresImageGeneration,
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

  const currentLlmName = currentDescriptor?.modelName;

  return (
    <Select
      value={currentLlm ? currentLlm : "default"}
      onValueChange={(value) => onSelect(value === "default" ? null : value)}
    >
      <SelectTrigger className="min-w-40">
        <SelectValue>
          {currentLlmName
            ? getDisplayNameForModel(currentLlmName)
            : userSettings
              ? "System Default"
              : "User Default"}
        </SelectValue>
      </SelectTrigger>
      <SelectContent className="z-[99999]">
        <SelectItem className="flex" hideCheck value="default">
          <span>{userSettings ? "System Default" : "User Default"}</span>
          {userSettings && (
            <span className=" my-auto font-normal ml-1">
              ({defaultModelDisplayName})
            </span>
          )}
        </SelectItem>
        {llmOptions.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            <div className="my-1 flex items-center">
              {option.icon && option.icon({ size: 16 })}
              <span className="ml-2">{option.name}</span>
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
};
