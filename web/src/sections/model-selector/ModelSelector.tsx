"use client";

import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import type { ReactNode } from "react";
import { Popover } from "@opal/components";
import { getModelIcon } from "@/lib/languageModels";
import { Slider } from "@/components/ui/slider";
import { useUser } from "@/providers/UserProvider";
import Text from "@/refresh-components/texts/Text";
import { OpenButton } from "@opal/components";
import { LLMOption, ProviderForOptions } from "@/lib/languageModels/options";
import ModelSelectorContent from "./ModelSelectorContent";
import { useLLMProviders } from "@/hooks/useLanguageModels";

interface CurrentOption {
  displayName: string;
  provider: string;
  modelName: string;
}

export interface ModelSelectorProps {
  /** model_configuration.id of the currently selected model; null = none. */
  value: number | null;
  onChange: (id: number | null) => void;
  requiresImageInput?: boolean;
  /**
   * Custom trigger element. Receives the currently selected option (or null).
   * When omitted, defaults to an OpenButton showing the model name and icon.
   */
  renderTrigger?: (currentOption: CurrentOption | null) => ReactNode;
  disabled?: boolean;
  /** Temperature value (0–maxTemperature). Slider is hidden when omitted. */
  temperature?: number;
  maxTemperature?: number;
  onTemperatureCommit?: (value: number) => void;
  /** Explicit persona ID for provider scoping; overrides auto-detection via useCurrentAgent. */
  personaId?: number;
  /** Pre-fetched providers (e.g. from the admin endpoint). When provided, skips useLLMProviders. */
  providers?: ProviderForOptions[];
}

export default function ModelSelector({
  value,
  onChange,
  requiresImageInput,
  renderTrigger,
  disabled = false,
  temperature,
  maxTemperature,
  onTemperatureCommit,
  personaId,
  providers,
}: ModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const { user } = useUser();
  const { llmProviders: fetched, isLoading } = useLLMProviders(personaId);
  const llmProviders = providers ?? fetched;

  const [localTemperature, setLocalTemperature] = useState(temperature ?? 0.5);

  useEffect(() => {
    setLocalTemperature(temperature ?? 0.5);
  }, [temperature]);

  // Find the currently selected model by ID across all providers.
  const currentOption = useMemo((): CurrentOption | null => {
    if (value == null || !llmProviders) return null;
    for (const p of llmProviders) {
      const mc = p.model_configurations.find((m) => m.id === value);
      if (mc) {
        return {
          displayName: mc.display_name || mc.name,
          provider: p.provider,
          modelName: mc.name,
        };
      }
    }
    return null;
  }, [value, llmProviders]);

  const isSelected = useCallback(
    (option: LLMOption) =>
      option.modelConfigId != null && option.modelConfigId === value,
    [value]
  );

  const handleSelect = useCallback(
    (option: LLMOption) => {
      onChange(option.modelConfigId);
      setOpen(false);
    },
    [onChange]
  );

  const handleTemperatureChange = useCallback((v: number[]) => {
    const val = v[0];
    if (val !== undefined) setLocalTemperature(val);
  }, []);

  const handleTemperatureCommit = useCallback(
    (v: number[]) => {
      const val = v[0];
      if (val !== undefined) onTemperatureCommit?.(val);
    },
    [onTemperatureCommit]
  );

  const showTemperature =
    temperature !== undefined &&
    maxTemperature !== undefined &&
    user?.preferences?.temperature_override_enabled;

  const temperatureFooter = showTemperature ? (
    <>
      <div className="border-t border-border-02 mx-2" />
      <div className="flex flex-col w-full py-2 gap-2">
        <Slider
          value={[localTemperature]}
          max={maxTemperature}
          min={0}
          step={0.01}
          onValueChange={handleTemperatureChange}
          onValueCommit={handleTemperatureCommit}
          className="w-full"
        />
        <div className="flex flex-row items-center justify-between">
          <Text secondaryBody text03>
            Temperature (creativity)
          </Text>
          <Text secondaryBody text03>
            {localTemperature.toFixed(1)}
          </Text>
        </div>
      </div>
    </>
  ) : undefined;

  return (
    <Popover
      open={open}
      onOpenChange={(o: boolean) => {
        if (disabled && o) return;
        setOpen(o);
      }}
    >
      <div data-testid="model-selector">
        <Popover.Trigger asChild disabled={disabled}>
          {renderTrigger ? (
            renderTrigger(currentOption)
          ) : (
            <OpenButton
              disabled={disabled}
              icon={
                currentOption
                  ? getModelIcon(
                      currentOption.provider,
                      currentOption.modelName
                    )
                  : undefined
              }
            >
              {currentOption?.displayName ?? "Select a model"}
            </OpenButton>
          )}
        </Popover.Trigger>
      </div>

      <Popover.Content side="top" align="end" width="xl">
        <ModelSelectorContent
          requiresImageInput={requiresImageInput}
          onSelect={handleSelect}
          isSelected={isSelected}
          footer={temperatureFooter}
          personaId={personaId}
          providers={providers}
        />
      </Popover.Content>
    </Popover>
  );
}
