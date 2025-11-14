import { useState, useEffect, useCallback, useMemo } from "react";
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
import SvgRefreshCw from "@/icons/refresh-cw";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
export interface LLMPopoverProps {
  llmManager: LlmManager;
  requiresImageGeneration?: boolean;
  folded?: boolean;
  onSelect?: (value: string) => void;
  currentModelName?: string;
  disabled?: boolean;
}

export default function LLMPopover({
  llmManager,
  requiresImageGeneration,
  folded,
  onSelect,
  currentModelName,
  disabled = false,
}: LLMPopoverProps) {
  const llmProviders = llmManager.llmProviders;
  const isLoadingProviders = llmManager.isLoadingProviders;

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

  const llmOptionsToChooseFrom = useMemo(() => {
    if (!llmProviders) {
      return [];
    }

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
      <PopoverTrigger asChild disabled={disabled}>
        <div data-testid="llm-popover-trigger">
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
            transient={open}
            folded={folded}
            rightChevronIcon
            disabled={disabled}
            className={disabled ? "bg-transparent" : ""}
          >
            {getDisplayNameForModel(llmManager.currentLlm.modelName)}
          </SelectButton>
        </div>
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
          {isLoadingProviders
            ? [
                <LineItem key="loading" icon={SimpleLoader}>
                  Loading models...
                </LineItem>,
              ]
            : llmOptionsToChooseFrom.map(
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
