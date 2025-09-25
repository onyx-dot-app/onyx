import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  getDisplayNameForModel,
  LlmDescriptor,
  useLlmManager,
} from "@/lib/hooks";
import { modelSupportsImageInput, structureValue } from "@/lib/llm/utils";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
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
import { useAgentsContext } from "@/components-2/context/AgentsContext";
import { useChatContext } from "@/components-2/context/ChatContext";
import { SelectButton } from "@/components-2/buttons/SelectButton";
import SvgRefreshCw from "@/icons/refresh-cw";
import { IconButton } from "@/components-2/buttons/IconButton";

export interface LLMPopoverProps {
  compact?: boolean;
  requiresImageGeneration?: boolean;
  onSelect?: (value: string) => void;
  currentModelName?: string;
  align?: "start" | "center" | "end";
}

export default function LLMPopover({
  compact,
  requiresImageGeneration,
  onSelect,
  currentModelName,
  align,
}: LLMPopoverProps) {
  const { user } = useUser();
  const { llmProviders, currentChat } = useChatContext();
  const { currentAgent } = useAgentsContext();
  const llmManager = useLlmManager(
    llmProviders,
    currentChat || undefined,
    currentAgent || undefined
  );
  const [open, setOpen] = useState(false);

  const [localTemperature, setLocalTemperature] = useState(
    llmManager.temperature ?? 0.5
  );

  useEffect(() => {
    setLocalTemperature(llmManager.temperature ?? 0.5);
  }, [llmManager.temperature]);

  // Use useCallback to prevent function recreation
  const handleTemperatureChange = useCallback((value: number[]) => {
    const value_0 = value[0];
    if (value_0 !== undefined) {
      setLocalTemperature(value_0);
    }
  }, []);

  const handleTemperatureChangeComplete = useCallback(
    (value: number[]) => {
      const value_0 = value[0];
      if (value_0 !== undefined) {
        llmManager.updateTemperature(value_0);
      }
    },
    [llmManager]
  );

  // Memoize trigger content to prevent rerendering
  const triggerContent = useMemo(
    () =>
      compact ? (
        <IconButton icon={SvgRefreshCw} tertiary active={open} />
      ) : (
        <SelectButton
          icon={getProviderIcon(
            llmManager.currentLlm.provider,
            llmManager.currentLlm.modelName
          )}
          active={open}
        >
          {getDisplayNameForModel(llmManager.currentLlm.modelName)}
        </SelectButton>
      ),
    [llmManager.currentLlm, open]
  );

  const llmOptionsToChooseFrom = useMemo(
    () =>
      llmProviders.flatMap((llmProvider) =>
        llmProvider.model_configurations
          .filter(
            (modelConfiguration) =>
              modelConfiguration.is_visible ||
              modelConfiguration.name === currentModelName
          )
          .map((modelConfiguration) => ({
            name: llmProvider.name,
            provider: llmProvider.provider,
            modelName: modelConfiguration.name,
            icon: getProviderIcon(
              llmProvider.provider,
              modelConfiguration.name
            ),
          }))
      ),
    [llmProviders]
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <div>{triggerContent}</div>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="center"
        className="w-64 p-1 bg-background-tint-01 border shadow-lg flex flex-col"
      >
        <div className="flex-grow max-h-[300px] default-scrollbar overflow-y-auto">
          {llmOptionsToChooseFrom.map(
            ({ modelName, provider, name, icon }, index) => {
              if (
                !requiresImageGeneration ||
                modelSupportsImageInput(llmProviders, modelName, name)
              ) {
                return (
                  <button
                    key={index}
                    className={`w-full flex items-center gap-x-2 px-3 py-2 text-sm text-left hover:bg-background-tint-03 text-text-04 ${(currentModelName || llmManager.currentLlm.modelName) === modelName && "bg-background-tint-02"}`}
                    onClick={() => {
                      llmManager.updateCurrentLlm({
                        modelName,
                        provider,
                        name,
                      } as LlmDescriptor);
                      onSelect?.(structureValue(name, provider, modelName));
                      setOpen(false);
                    }}
                  >
                    {icon({
                      size: 16,
                      className: "flex-none my-auto",
                    })}
                    <TruncatedText text={getDisplayNameForModel(modelName)} />
                    {(() => {
                      if (
                        currentAgent?.llm_model_version_override === modelName
                      ) {
                        return (
                          <span className="flex-none ml-auto text-xs">
                            (assistant)
                          </span>
                        );
                      }
                    })()}
                    {llmManager.imageFilesPresent &&
                      !modelSupportsImageInput(
                        llmProviders,
                        modelName,
                        provider
                      ) && (
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger className="my-auto flex items-center ml-auto">
                              <FiAlertTriangle
                                className="text-status-warning-05"
                                size={16}
                              />
                            </TooltipTrigger>
                            <TooltipContent>
                              <p className="text-xs">
                                This LLM is not vision-capable and cannot
                                process image files present in your chat
                                session.
                              </p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      )}
                  </button>
                );
              }
              return null;
            }
          )}
        </div>
        {user?.preferences?.temperature_override_enabled && (
          <div className="mt-2 pt-2 border-t border-border-01">
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
              <div className="flex justify-between text-xs mt-2">
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
