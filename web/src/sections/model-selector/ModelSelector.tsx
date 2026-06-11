"use client";

import React, {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
} from "react";
import { Popover, OpenButton, Text } from "@opal/components";
import { Slider } from "@/components/ui/slider";
import { getModelIcon } from "@/lib/languageModels";
import { LLMOption } from "@/lib/languageModels/options";
import { LLMProviderDescriptor } from "@/lib/languageModels/types";
import { useUser } from "@/providers/UserProvider";
import ModelSelectorContent from "@/sections/model-selector/ModelSelectorContent";

interface TemperatureManager {
  temperature: number;
  updateTemperature: (value: number) => void;
  maxTemperature: number;
}

export interface ModelSelectorProps {
  llmProviders: LLMProviderDescriptor[] | undefined;
  /** The currently selected model, identified by model_configuration_id. */
  value: number | null;
  onChange: (option: LLMOption) => void;
  requiresImageInput?: boolean;

  /**
   * Custom trigger element. When omitted the default OpenButton (icon +
   * display name) is rendered.
   */
  renderTrigger?: () => React.ReactNode;

  /**
   * When provided, a temperature slider is shown at the bottom of the
   * popover (gated on user.preferences.temperature_override_enabled).
   */
  temperatureManager?: TemperatureManager;

  disabled?: boolean;
  isLoading?: boolean;
}

export default function ModelSelector({
  llmProviders,
  value,
  onChange,
  requiresImageInput,
  renderTrigger,
  temperatureManager,
  disabled = false,
  isLoading,
}: ModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const { user } = useUser();
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Resolve the currently selected option from the ID
  const currentOption = useMemo(() => {
    if (value == null || !llmProviders) return null;
    for (const provider of llmProviders) {
      const mc = provider.model_configurations.find((m) => m.id === value);
      if (mc) {
        return {
          provider: provider.provider,
          modelName: mc.name,
          displayName: mc.custom_display_name ?? mc.display_name ?? mc.name,
        };
      }
    }
    return null;
  }, [value, llmProviders]);

  const currentDisplayName = currentOption?.displayName ?? "Select Model";

  const isSelected = useCallback(
    (option: LLMOption) =>
      option.modelConfigurationId != null
        ? option.modelConfigurationId === value
        : option.provider === currentOption?.provider &&
          option.modelName === currentOption?.modelName,
    [value, currentOption]
  );

  const handleSelect = useCallback(
    (option: LLMOption) => {
      onChange(option);
      setOpen(false);
    },
    [onChange]
  );

  // Temperature state — only used when temperatureManager is provided
  const [localTemperature, setLocalTemperature] = useState(
    temperatureManager?.temperature ?? 0.5
  );

  useEffect(() => {
    if (temperatureManager) {
      setLocalTemperature(temperatureManager.temperature ?? 0.5);
    }
  }, [temperatureManager?.temperature]);

  const handleTemperatureChange = useCallback((vals: number[]) => {
    if (vals[0] !== undefined) setLocalTemperature(vals[0]);
  }, []);

  const handleTemperatureCommit = useCallback(
    (vals: number[]) => {
      if (vals[0] !== undefined) temperatureManager?.updateTemperature(vals[0]);
    },
    [temperatureManager]
  );

  const temperatureFooter =
    temperatureManager && user?.preferences?.temperature_override_enabled ? (
      <>
        <div className="border-t border-border-02 mx-2" />
        <div className="flex flex-col w-full py-2 gap-2">
          <Slider
            value={[localTemperature]}
            max={temperatureManager.maxTemperature}
            min={0}
            step={0.01}
            onValueChange={handleTemperatureChange}
            onValueCommit={handleTemperatureCommit}
            className="w-full"
          />
          <div className="flex flex-row items-center justify-between">
            <Text font="secondary-body" color="text-03">
              Temperature (creativity)
            </Text>
            <Text font="secondary-body" color="text-03">
              {localTemperature.toFixed(1)}
            </Text>
          </div>
        </div>
      </>
    ) : undefined;

  const triggerIcon = currentOption
    ? getModelIcon(currentOption.provider, currentOption.modelName)
    : getModelIcon("", "");

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <div data-testid="llm-popover-trigger">
        <Popover.Trigger asChild disabled={disabled}>
          {renderTrigger ? (
            renderTrigger()
          ) : (
            <OpenButton disabled={disabled} icon={triggerIcon}>
              {currentDisplayName}
            </OpenButton>
          )}
        </Popover.Trigger>
      </div>

      <Popover.Content side="top" align="end" width="xl">
        <ModelSelectorContent
          llmProviders={llmProviders}
          currentModelName={currentOption?.modelName}
          requiresImageInput={requiresImageInput}
          isLoading={isLoading}
          onSelect={handleSelect}
          isSelected={isSelected}
          scrollContainerRef={scrollContainerRef}
          footer={temperatureFooter}
        />
      </Popover.Content>
    </Popover>
  );
}
