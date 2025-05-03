import React from "react";
import { getDisplayNameForModel } from "@/lib/hooks";
import {
  destructureValue,
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
  const seenModelNames = new Set();

  const llmOptions = llmProviders.flatMap((provider) => {
    return provider.model_configurations
      .filter((modelConfiguration) => {
        const displayName = getDisplayNameForModel(modelConfiguration.name);
        if (seenModelNames.has(displayName)) {
          return false;
        }
        seenModelNames.add(displayName);
        return true;
      })
      .map((modelConfiguration) => ({
        name: getDisplayNameForModel(modelConfiguration.name),
        value: structureValue(
          provider.name,
          provider.provider,
          modelConfiguration.name
        ),
        icon: getProviderIcon(provider.provider, modelConfiguration.name),
      }));
  });

  const defaultProvider = llmProviders.find(
    (llmProvider) => llmProvider.is_default_provider
  );

  const defaultModelName = defaultProvider?.default_model_name;
  const defaultModelDisplayName = defaultModelName
    ? getDisplayNameForModel(defaultModelName)
    : null;

  const destructuredCurrentValue = currentLlm
    ? destructureValue(currentLlm)
    : null;

  const currentLlmName = destructuredCurrentValue?.modelName;

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
        {llmOptions.map((option) => {
          if (
            !requiresImageGeneration ||
            modelSupportsImageInput(llmProviders, option.name)
          ) {
            return (
              <SelectItem key={option.value} value={option.value}>
                <div className="my-1 flex items-center">
                  {option.icon && option.icon({ size: 16 })}
                  <span className="ml-2">{option.name}</span>
                </div>
              </SelectItem>
            );
          }
        })}
      </SelectContent>
    </Select>
  );
};
