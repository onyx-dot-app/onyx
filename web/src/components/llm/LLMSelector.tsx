import React from "react";
import { getDisplayNameForModel } from "@/lib/hooks";
import {
  checkLLMSupportsImageInput,
  destructureValue,
  structureValue,
} from "@/lib/llm/utils";
import {
  getProviderIcon,
  LLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface LLMSelectorProps {
  llmProviders: LLMProviderDescriptor[];
  currentLlm: string | null;
  onSelect: (value: string | null) => void;
  userDefault?: string | null;
  requiresImageGeneration?: boolean;
}

export const LLMSelector: React.FC<LLMSelectorProps> = ({
  llmProviders,
  currentLlm,
  onSelect,
  userDefault,
  requiresImageGeneration,
}) => {
  const llmOptions = llmProviders.flatMap((provider) =>
    (provider.display_model_names || provider.model_names).map((modelName) => ({
      name: getDisplayNameForModel(modelName),
      value: structureValue(provider.name, provider.provider, modelName),
      icon: getProviderIcon(provider.provider, modelName),
    }))
  );

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
            : "User Default"}
        </SelectValue>
      </SelectTrigger>
      <SelectContent className="z-[99999]">
        <SelectItem hideCheck value="default">
          User Default
        </SelectItem>
        {llmOptions.map((option) => {
          if (
            !requiresImageGeneration ||
            checkLLMSupportsImageInput(option.name)
          ) {
            return (
              <SelectItem key={option.value} value={option.value}>
                <div className="mt-2 flex items-center">
                  {option.icon && option.icon({ size: 16 })}
                  <span className="ml-2">{option.name}</span>
                  {userDefault &&
                    option.value ===
                      structureValue(userDefault, "", userDefault) && (
                      <span className="ml-2 text-sm text-gray-500">
                        (user default)
                      </span>
                    )}
                </div>
              </SelectItem>
            );
          }
          return null;
        })}
      </SelectContent>
    </Select>
  );
};
