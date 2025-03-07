import React, {
  useState,
  useEffect,
  useCallback,
  useLayoutEffect,
} from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ChatInputOption } from "./ChatInputOption";
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
import { LlmManager } from "@/lib/hooks";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { FiAlertTriangle } from "react-icons/fi";

import { Slider } from "@/components/ui/slider";
import { useUser } from "@/components/user/UserProvider";
import { TruncatedText } from "@/components/ui/truncatedText";

interface LLMPopoverProps {
  llmProviders: LLMProviderDescriptor[];
  llmManager: LlmManager;
  requiresImageGeneration?: boolean;
  currentAssistant?: Persona;
}

export default function LLMPopover({
  llmProviders,
  llmManager,
  requiresImageGeneration,
  currentAssistant,
}: LLMPopoverProps) {
  const [isOpen, setIsOpen] = useState(false);
  const { user } = useUser();

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

  const defaultProvider = llmProviders.find(
    (llmProvider) => llmProvider.is_default_provider
  );

  const defaultModelName = defaultProvider?.default_model_name;
  const defaultModelDisplayName = defaultModelName
    ? getDisplayNameForModel(defaultModelName)
    : null;

  const [localTemperature, setLocalTemperature] = useState(
    llmManager.temperature ?? 0.5
  );

  useEffect(() => {
    setLocalTemperature(llmManager.temperature ?? 0.5);
  }, [llmManager.temperature]);

  const handleTemperatureChange = (value: number[]) => {
    setLocalTemperature(value[0]);
  };

  const handleTemperatureChangeComplete = (value: number[]) => {
    llmManager.updateTemperature(value[0]);
  };

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <button
          className="dark:text-[#fff] text-[#000] focus:outline-none"
          data-testid="llm-popover-trigger"
        >
          <ChatInputOption
            minimize
            toggle
            flexPriority="stiff"
            name={getDisplayNameForModel(
              llmManager?.currentLlm.modelName ||
                defaultModelDisplayName ||
                "Models"
            )}
            Icon={getProviderIcon(
              llmManager?.currentLlm.provider ||
                defaultProvider?.provider ||
                "anthropic",
              llmManager?.currentLlm.modelName ||
                defaultProvider?.default_model_name ||
                "claude-3-5-sonnet-20240620"
            )}
            tooltipContent="Switch models"
          />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-64 p-1 bg-background border border-background-200 rounded-md shadow-lg flex flex-col"
      >
        <div className="flex-grow max-h-[300px] default-scrollbar overflow-y-auto">
          {llmOptions.map(({ name, icon, value }, index) => {
            if (!requiresImageGeneration || checkLLMSupportsImageInput(name)) {
              return (
                <button
                  key={index}
                  className={`w-full flex items-center gap-x-2 px-3 py-2 text-sm text-left hover:bg-background-100 dark:hover:bg-neutral-800 transition-colors duration-150 ${
                    llmManager.currentLlm.modelName === name
                      ? "bg-background-100 dark:bg-neutral-900 text-text"
                      : "text-text-darker"
                  }`}
                  onClick={() => {
                    llmManager.updateCurrentLlm(destructureValue(value));
                    setIsOpen(false);
                  }}
                >
                  {icon({
                    size: 16,
                    className: "flex-none my-auto text-black",
                  })}
                  <TruncatedText text={getDisplayNameForModel(name)} />
                  {(() => {
                    if (currentAssistant?.llm_model_version_override === name) {
                      return (
                        <span className="flex-none ml-auto text-xs">
                          (assistant)
                        </span>
                      );
                    }
                  })()}
                  {llmManager.imageFilesPresent &&
                    !checkLLMSupportsImageInput(name) && (
                      <TooltipProvider>
                        <Tooltip delayDuration={0}>
                          <TooltipTrigger className="my-auto flex items-center ml-auto">
                            <FiAlertTriangle className="text-alert" size={16} />
                          </TooltipTrigger>
                          <TooltipContent>
                            <p className="text-xs">
                              This LLM is not vision-capable and cannot process
                              image files present in your chat session.
                            </p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    )}
                </button>
              );
            }
            return null;
          })}
        </div>
        {user?.preferences?.temperature_override_enabled && (
          <div className="mt-2 pt-2 border-t border-background-200">
            <div className="w-full px-3 py-2">
              <Slider
                value={[localTemperature]}
                max={llmManager.maxTemperature}
                min={0}
                step={0.01}
                onValueChange={handleTemperatureChange}
                onValueCommit={handleTemperatureChangeComplete}
                className="w-full"
              />
              <div className="flex justify-between text-xs text-text-500 mt-2">
                <span>Temperature (creativity)</span>
                <span>{localTemperature.toFixed(1)}</span>
              </div>
            </div>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
