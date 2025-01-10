import React from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ChatInputOption } from "./ChatInputOption";
import { AnthropicSVG } from "@/components/icons/icons";
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
import { LlmOverrideManager } from "@/lib/hooks";

interface LLMPopoverProps {
  llmProviders: LLMProviderDescriptor[];
  llmOverrideManager: LlmOverrideManager;
  requiresImageGeneration?: boolean;
  currentAssistant?: Persona;
}

export default function LLMPopover({
  llmProviders,
  llmOverrideManager,
  requiresImageGeneration,
  currentAssistant,
}: LLMPopoverProps) {
  const { llmOverride, updateLLMOverride, globalDefault } = llmOverrideManager;
  const currentLlm = llmOverride.modelName || globalDefault.modelName;

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
    <Popover>
      <PopoverTrigger asChild>
        <button className="focus:outline-none">
          <ChatInputOption
            toggle
            flexPriority="stiff"
            name="Models"
            Icon={AnthropicSVG}
            tooltipContent="Switch models"
          />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-1 bg-white border border-gray-200 rounded-md shadow-lg">
        <div className="max-h-[300px] overflow-y-auto">
          {llmOptions.map(({ name, icon, value }, index) => {
            if (!requiresImageGeneration || checkLLMSupportsImageInput(name)) {
              return (
                <button
                  key={index}
                  className={`w-full flex items-center gap-x-2 px-3 py-2 text-sm text-left hover:bg-gray-100 transition-colors duration-150 ${
                    currentLlm === name
                      ? "bg-gray-100 text-text"
                      : "text-text-darker"
                  }`}
                  onClick={() => updateLLMOverride(destructureValue(value))}
                >
                  <div className="relative flex-shrink-0">
                    <div
                      className={`w-4 h-4 rounded-full border ${
                        currentLlm === name
                          ? "border-gray-700"
                          : "border-gray-300"
                      }`}
                    >
                      {currentLlm === name && (
                        <div className="absolute inset-0 flex items-center justify-center">
                          <div className="w-2 h-2 rounded-full bg-gray-700"></div>
                        </div>
                      )}
                    </div>
                  </div>
                  {icon({ size: 16, className: "flex-none my-auto " })}
                  <span className="line-clamp-1 ">
                    {getDisplayNameForModel(name)}
                  </span>
                  {(() => {
                    if (currentAssistant?.llm_model_version_override === name) {
                      return (
                        <span className="flex-none ml-auto text-xs">
                          (assistant)
                        </span>
                      );
                    } else if (globalDefault.modelName === name) {
                      return (
                        <span className="flex-none ml-auto text-xs">
                          (user default)
                        </span>
                      );
                    }
                    return null;
                  })()}
                </button>
              );
            }
            return null;
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
