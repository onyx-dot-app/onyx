import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { getDisplayNameForModel, LlmDescriptor, LlmManager } from "@/lib/hooks";
import { modelSupportsImageInput, structureValue } from "@/lib/llm/utils";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import { Slider } from "@/components/ui/slider";
import { useUser } from "@/components/user/UserProvider";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import SvgRefreshCw from "@/icons/refresh-cw";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";

interface LLMPopoverProps {
  llmManager: LlmManager;
  requiresImageGeneration?: boolean;
  folded?: boolean;
  onSelect?: (value: string) => void;
  currentModelName?: string;
}

export default function LLMPopover({
  llmManager,
  requiresImageGeneration,
  folded,
  onSelect,
  currentModelName,
}: LLMPopoverProps) {
  const { llmProviders } = useChatContext();

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
            : getProviderIcon(
                llmManager.currentLlm.provider,
                llmManager.currentLlm.modelName
              )
        }
        onClick={() => setOpen(true)}
        active={open}
        folded={folded}
        rightChevronIcon
      >
        {getDisplayNameForModel(llmManager.currentLlm.modelName)}
      </SelectButton>
    ),
    [
      llmManager.currentLlm.modelName,
      llmManager.currentLlm.provider,
      open,
      folded,
    ]
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
        <div data-testid="llm-popover-trigger">{triggerContent}</div>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        className="max-h-[20rem] w-[15rem] p-spacing-inline border rounded-08 shadow-lg flex flex-col"
      >
        <div className="overflow-y-scroll">
          {llmOptionsToChooseFrom.map(
            ({ modelName, provider, name, icon }, index) => {
              if (
                requiresImageGeneration &&
                !modelSupportsImageInput(llmProviders, modelName, name)
              )
                return null;
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
        </div>
        {user?.preferences?.temperature_override_enabled && (
          <div className="flex flex-col w-full py-padding-button px-spacing-interline gap-spacing-interline">
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
        )}
      </PopoverContent>
    </Popover>
  );
}
