import React from "react";
import { getDisplayNameForModel } from "@/lib/hooks";
import { checkLLMSupportsImageInput, structureValue } from "@/lib/llm/utils";
import {
  getProviderIcon,
  LLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { FiAlertTriangle } from "react-icons/fi";

interface LlmListProps {
  llmProviders: LLMProviderDescriptor[];
  currentLlm: string;
  onSelect: (value: string | null) => void;
  userDefault?: string | null;
  scrollable?: boolean;
  hideProviderIcon?: boolean;
  imageFilesPresent?: boolean;
}

export const LlmList: React.FC<LlmListProps> = ({
  llmProviders,
  currentLlm,
  onSelect,
  userDefault,
  scrollable,
  imageFilesPresent,
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
            icon: getProviderIcon(llmProvider.provider),
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
        scrollable ? "max-h-[200px] include-scrollbar" : "max-h-[300px]"
      } bg-background-175 flex flex-col gap-y-1 overflow-y-scroll`}
    >
      {userDefault && (
        <button
          type="button"
          key={-1}
          className={`w-full py-1.5 px-2 text-sm ${
            currentLlm == null
              ? "bg-background-200"
              : "bg-background hover:bg-background-100"
          } text-left rounded`}
          onClick={() => onSelect(null)}
        >
          User Default (currently {getDisplayNameForModel(userDefault)})
        </button>
      )}

      {llmOptions.map(({ name, icon, value }, index) => (
        <button
          type="button"
          key={index}
          className={`w-full py-1.5 flex items-center justify-start  gap-x-2 px-2 text-sm ${
            currentLlm == name
              ? "bg-background-200"
              : "bg-background hover:bg-background-100"
          } text-left rounded`}
          onClick={() => onSelect(value)}
        >
          {icon({ size: 16 })}
          {getDisplayNameForModel(name)}
          {imageFilesPresent && !checkLLMSupportsImageInput(name) && (
            <TooltipProvider>
              <Tooltip delayDuration={0}>
                <TooltipTrigger className="my-auto flex ites-center ml-auto">
                  <FiAlertTriangle className="text-alert" size={16} />
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs">
                    This LLM is not vision-capable and cannot process image
                    files present in your chat session.
                  </p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
        </button>
      ))}
    </div>
  );
};
