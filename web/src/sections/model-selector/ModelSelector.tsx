"use client";

import React, { useState, useCallback, useMemo, useRef } from "react";
import { Popover } from "@opal/components";
import { useLanguageModels } from "@/lib/languageModels/hooks";
import ModelSelectorContent, {
  ReasoningManager,
  TemperatureManager,
  useModelDetailManagers,
} from "@/sections/model-selector/ModelSelectorContent";
import type {
  LLMOption,
  ModelOptionProvider,
  ModelPaging,
} from "@/lib/languageModels/types";

export interface ModelSelectorProps {
  /** The currently selected model, identified by model_configuration_id. */
  value: number | null;
  onChange: (option: LLMOption) => void;
  providerOptions?: ModelOptionProvider[];
  /** Pages in the models a host-supplied `providerOptions` list left out.
   *  Ignored when the selector fetches its own list, which pages itself. */
  modelPaging?: ModelPaging;

  /** The trigger element that opens the popover. */
  renderTrigger: () => React.ReactNode;

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
}

export default function ModelSelector({
  value,
  onChange,
  providerOptions,
  modelPaging: modelPagingProp,
  renderTrigger,
  temperatureManager,
  reasoningManager,
}: ModelSelectorProps) {
  // Unscoped by default. Callers must supply providerOptions when the host
  // has an agent context.
  // The list stays defined even before it arrives, so the child never sees
  // undefined and never falls through to its own agent-scoped list.
  const {
    llmProviders: fetchedProviderOptions,
    isLoading: providersLoading,
    modelPaging: fetchedModelPaging,
  } = useLanguageModels();
  const llmProviders = providerOptions ?? fetchedProviderOptions ?? [];
  const isLoading = providerOptions === undefined && providersLoading;
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

  const isSelected = useCallback(
    (option: LLMOption) => {
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

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <div data-testid="llm-popover-trigger">
        <Popover.Trigger asChild>{renderTrigger()}</Popover.Trigger>
      </div>

      <Popover.Content side="top" align="end" width="xl" sticky="partial">
        <ModelSelectorContent
          currentModelName={currentOption?.modelName}
          providerOptions={llmProviders}
          modelPaging={
            providerOptions === undefined ? fetchedModelPaging : modelPagingProp
          }
          isLoading={isLoading}
          onSelect={handleSelect}
          isSelected={isSelected}
          scrollContainerRef={scrollContainerRef}
          modelDetail={modelDetail}
          onDetailSelect={onChange}
        />
      </Popover.Content>
    </Popover>
  );
}
