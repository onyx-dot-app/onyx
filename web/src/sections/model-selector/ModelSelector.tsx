"use client";

import React, { useState, useCallback, useMemo, useRef } from "react";
import { Popover, OpenButton } from "@opal/components";
import { getModelIcon } from "@/lib/languageModels";
import {
  GLOBAL_DEFAULT_LLM_OPTION,
  LLMOption,
} from "@/lib/languageModels/options";
import { useCurrentAgentLLMProviders } from "@/lib/languageModels/hooks";
import ModelSelectorContent, {
  ReasoningManager,
  TemperatureManager,
  useModelDetailManagers,
} from "@/sections/model-selector/ModelSelectorContent";

export interface ModelSelectorProps {
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
   * When provided, a temperature slider is shown in the per-model detail
   * pane (gated on user.preferences.temperature_override_enabled).
   */
  temperatureManager?: TemperatureManager;

  /**
   * When provided, the reasoning-level slider in the per-model detail pane is
   * enabled for models that report supports_reasoning, disabled otherwise.
   */
  reasoningManager?: ReasoningManager;

  disabled?: boolean;
  /**
   * When true, a "Global Default Model" entry is prepended to the list.
   * Selecting it calls onChange with GLOBAL_DEFAULT_LLM_OPTION
   * (modelConfigurationId === null), which callers should treat as "clear."
   */
  includeGlobalDefault?: boolean;
  /** Which side of the trigger the popover prefers to open on. */
  side?: "top" | "bottom" | "left" | "right";
}

export default function ModelSelector({
  value,
  onChange,
  requiresImageInput,
  renderTrigger,
  temperatureManager,
  reasoningManager,
  disabled = false,
  includeGlobalDefault = false,
  side = "top",
}: ModelSelectorProps) {
  const { llmProviders, defaultText } = useCurrentAgentLLMProviders();
  const [open, setOpen] = useState(false);
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
          displayName: mc.effectiveDisplayName,
        };
      }
    }
    return null;
  }, [value, llmProviders]);

  // When no model is explicitly selected, fall back to showing the global default.
  const defaultModelOption = useMemo(() => {
    if (!defaultText || !llmProviders) return null;
    const provider = llmProviders.find((p) => p.id === defaultText.provider_id);
    const mc = provider?.model_configurations.find(
      (m) => m.name === defaultText.model_name
    );
    if (!mc || !provider) return null;
    return {
      provider: provider.provider,
      modelName: mc.name,
      displayName: mc.custom_display_name ?? mc.display_name ?? mc.name,
    };
  }, [defaultText, llmProviders]);

  const effectiveOption = currentOption ?? defaultModelOption;
  const currentDisplayName = effectiveOption?.displayName ?? "Select Model";

  const isSelected = useCallback(
    (option: LLMOption) => {
      if (option === GLOBAL_DEFAULT_LLM_OPTION) return value === null;
      return option.modelConfigurationId != null
        ? option.modelConfigurationId === value
        : option.provider === currentOption?.provider &&
            option.modelName === currentOption?.modelName;
    },
    [value, currentOption]
  );

  const handleSelect = useCallback(
    (option: LLMOption) => {
      onChange(option);
      setOpen(false);
    },
    [onChange]
  );

  const modelDetail = useModelDetailManagers(
    temperatureManager,
    reasoningManager
  );

  const triggerIcon = effectiveOption
    ? getModelIcon(effectiveOption.provider, effectiveOption.modelName)
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

      <Popover.Content side={side} align="end" width="xl" sticky="partial">
        <ModelSelectorContent
          currentModelName={currentOption?.modelName}
          requiresImageInput={requiresImageInput}
          onSelect={handleSelect}
          isSelected={isSelected}
          includeGlobalDefault={includeGlobalDefault}
          scrollContainerRef={scrollContainerRef}
          modelDetail={modelDetail}
        />
      </Popover.Content>
    </Popover>
  );
}
