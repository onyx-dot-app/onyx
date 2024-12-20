import React, { useState, useRef } from "react";
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
  onClose: () => void;
}

export const LlmList: React.FC<LlmListProps> = ({
  currentAssistant,
  llmProviders,
  currentLlm,
  onSelect,
  userDefault,
  scrollable,
  requiresImageGeneration,
  onClose,
}) => {
  const [searchText, setSearchText] = useState("");
    const searchInputRef = useRef<HTMLInputElement>(null);


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

  const filteredOptions = llmOptions.filter((option) =>
    option.name.toLowerCase().includes(searchText.toLowerCase())
  );

  const displayedOptions = searchText ? filteredOptions : llmOptions;

    const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
        if (event.key === "Enter") {
            if (filteredOptions.length > 0) {
                onSelect(filteredOptions[0].value);
                onClose();
            }
        }
    };


  return (
    <div className="flex flex-col">
      {llmOptions.length > 6 && (
        <input
            ref={searchInputRef}
          type="text"
          placeholder="Search models..."
          className="w-full p-2 mb-2 border border-border rounded-md text-black"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
            onKeyDown={handleKeyDown}
        />
      )}
      <div
        className={`${
          scrollable
            ? "max-h-[200px] default-scrollbar overflow-x-hidden"
            : llmOptions.length > 6 ? "max-h-[180px]" : ""
        } bg-background-175 flex flex-col gap-y-1 overflow-y-scroll`}
      >
        {displayedOptions.map(({ name, icon, value }, index) => {
          if (!requiresImageGeneration || checkLLMSupportsImageInput(name)) {
            return (
              <button
                type="button"
                key={index}
                className={`w-full py-1.5 flex  gap-x-2 px-2 text-sm ${
                  currentLlm == name
                    ? "bg-background-200"
                    : "bg-background hover:bg-background-100"
                } text-left rounded`}
                onClick={() => onSelect(value)}
              >
                {icon({ size: 16 })}
                {getDisplayNameForModel(name)}
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
      {llmOptions.length > 7 && !searchText && (
        <div className="text-sm text-gray-500 mt-1 px-2">
          {llmOptions.length} models available
        </div>
      )}
      {searchText && (
        <div className="text-sm text-gray-500 mt-1 px-2">
          {filteredOptions.length} entries
        </div>
      )}
    </div>
  );
};
