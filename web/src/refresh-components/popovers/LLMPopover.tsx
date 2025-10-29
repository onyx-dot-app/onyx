import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import { getDisplayNameForModel, LlmDescriptor, LlmManager } from "@/lib/hooks";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { modelSupportsImageInput, structureValue } from "@/lib/llm/utils";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import { Slider } from "@/components/ui/slider";
import { useUser } from "@/components/user/UserProvider";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import SvgRefreshCw from "@/icons/refresh-cw";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";

export interface LLMPopoverProps {
  llmManager: LlmManager;
  requiresImageGeneration?: boolean;
  folded?: boolean;
  onSelect?: (value: string) => void;
  currentModelName?: string;
  llmProviders?: LLMProviderDescriptor[];
}

function LLMPopover({
  llmManager,
  requiresImageGeneration,
  folded,
  onSelect,
  currentModelName,
  llmProviders: propLlmProviders,
}: LLMPopoverProps) {
  const { llmProviders: contextLlmProviders } = useChatContext();

  // Use providers from props if provided, otherwise fall back to context
  const llmProviders = propLlmProviders ?? contextLlmProviders;

  const [open, setOpen] = useState(false);
  const { user } = useUser();
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
    () => (
      <SelectButton
        leftIcon={
          folded
            ? SvgRefreshCw
            : llmManager.isLoadingProviders
              ? SimpleLoader
              : getProviderIcon(
                  llmManager.currentLlm.provider,
                  llmManager.currentLlm.modelName
                )
        }
        onClick={() => setOpen(true)}
        active={open}
        folded={folded}
        rightChevronIcon
        disabled={llmManager.isLoadingProviders}
      >
        {getDisplayNameForModel(
          llmManager.currentLlm.modelName,
          llmManager.isLoadingProviders
        )}
      </SelectButton>
    ),
    [
      llmManager.currentLlm.modelName,
      llmManager.currentLlm.provider,
      llmManager.isLoadingProviders,
      open,
      folded,
    ]
  );

  const llmOptionsToChooseFrom = useMemo(() => {
    const options = llmProviders.flatMap((llmProvider) =>
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
          icon: getProviderIcon(llmProvider.provider, modelConfiguration.name),
        }))
    );

    return options;
  }, [llmProviders, currentModelName]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <div data-testid="llm-popover-trigger">{triggerContent}</div>
      </PopoverTrigger>
      <PopoverContent side="bottom" align="start">
        <PopoverMenu
          medium
          footer={
            user?.preferences?.temperature_override_enabled ? (
              <div className="flex flex-col w-full py-3 px-2 gap-2">
                <Slider
                  value={[localTemperature]}
                  max={llmManager.maxTemperature}
                  min={0}
                  step={0.01}
                  onValueChange={handleTemperatureChange}
                  onValueCommit={handleTemperatureChangeComplete}
                  className="w-full"
                />
                <div className="flex flex-row items-center justify-between">
                  <Text secondaryBody>Temperature (creativity)</Text>
                  <Text secondaryBody>{localTemperature.toFixed(1)}</Text>
                </div>
              </div>
            ) : undefined
          }
        >
          {llmOptionsToChooseFrom.map(
            ({ modelName, provider, name, icon }, index) => {
              return (
                <LineItem
                  key={index}
                  icon={({ className }) => icon({ size: 16, className })}
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
                  {getDisplayNameForModel(modelName)}
                </LineItem>
              );
            }
          )}
        </PopoverMenu>
      </PopoverContent>
    </Popover>
  );
}

// Memoize to prevent unnecessary re-renders when props haven't changed
export default React.memo(LLMPopover);
