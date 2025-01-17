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
import { Persona } from "@/app/admin/assistants/interfaces";

interface LlmListProps {
  llmProviders: LLMProviderDescriptor[];
  currentLlm: string;
  onSelect: (value: string | null) => void;
  userDefault?: string | null;
  scrollable?: boolean;
  hideProviderIcon?: boolean;
  requiresImageGeneration?: boolean;
  currentAssistant?: Persona;
}

export const LlmList: React.FC<LlmListProps> = ({
  currentAssistant,
  llmProviders,
  currentLlm,
  onSelect,
  userDefault,
  scrollable,
  requiresImageGeneration,
}) => {
  const llmOptionsByProvider: {
    [provider: string]: {
      name: string;
      value: string;
      icon: React.FC<{ size?: number; className?: string }>;
    }[];
  } = {};
  const uniqueModelNames = new Set<string>();

  llmProviders.forEach((llmProvider) => {
    if (!llmOptionsByProvider[llmProvider.provider]) {
      llmOptionsByProvider[llmProvider.provider] = [];
    }

    (llmProvider.display_model_names || llmProvider.model_names).forEach(
      (modelName) => {
        if (!uniqueModelNames.has(modelName)) {
          uniqueModelNames.add(modelName);
          llmOptionsByProvider[llmProvider.provider].push({
            name: modelName,
            value: structureValue(
              llmProvider.name,
              llmProvider.provider,
              modelName
            ),
            icon: getProviderIcon(llmProvider.provider, modelName),
          });
        }
      }
    );
  });

  const llmOptions = Object.entries(llmOptionsByProvider).flatMap(
    ([provider, options]) => [...options]
  );

  return (
    <div
      className={`${
        scrollable
          ? "max-h-[200px] default-scrollbar overflow-x-hidden"
          : "max-h-[300px]"
      } bg-background-175 flex flex-col gap-y-2 mt-1 overflow-y-scroll`}
    >
      {llmOptions.map(({ name, icon, value }, index) => {
        if (!requiresImageGeneration || checkLLMSupportsImageInput(name)) {
          return (
            <button
              type="button"
              key={index}
              className={`w-full items-center flex gap-x-2 text-sm  text-left rounded`}
              onClick={() => onSelect(value)}
            >
              <div className="relative  flex-shrink-0">
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 20 20"
                  fill="none"
                  className={`overflow-hidden rounded-full ${
                    currentLlm == name ? "bg-accent border-none " : ""
                  }`}
                  xmlns="http://www.w3.org/2000/svg"
                >
                  {currentLlm != name && (
                    <circle
                      cx="10"
                      cy="10"
                      r="9"
                      stroke="currentColor"
                      strokeWidth="1.5"
                    />
                  )}
                </svg>
              </div>
              {icon({ size: 16 })}
              <p className="text-sm">{getDisplayNameForModel(name)}</p>
              {(() => {
                if (
                  currentAssistant?.llm_model_version_override === name &&
                  userDefault &&
                  name === destructureValue(userDefault).modelName
                ) {
                  return " (assistant + user default)";
                } else if (
                  currentAssistant?.llm_model_version_override === name
                ) {
                  return " (assistant)";
                } else if (
                  userDefault &&
                  name === destructureValue(userDefault).modelName
                ) {
                  return " (user default)";
                }
                return "";
              })()}
            </button>
          );
        }
      })}
    </div>
  );
};
