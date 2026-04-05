"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import Popover from "@/refresh-components/Popover";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { structureValue } from "@/lib/llmConfig/utils";
import {
  getProviderIcon,
  AGGREGATOR_PROVIDERS,
} from "@/app/admin/configuration/llm/utils";
import { LLMProviderDescriptor } from "@/interfaces/llm";
import { Slider } from "@/components/ui/slider";
import { useUser } from "@/providers/UserProvider";
import Text from "@/refresh-components/texts/Text";
import { SvgRefreshCw } from "@opal/icons";
import { OpenButton } from "@opal/components";
import { LLMOption, LLMOptionGroup } from "./interfaces";
import ModelListContent from "./ModelListContent";

export interface LLMPopoverProps {
  llmManager: LlmManager;
  requiresImageInput?: boolean;
  foldable?: boolean;
  onSelect?: (value: string) => void;
  currentModelName?: string;
  disabled?: boolean;
}

export function buildLlmOptions(
  llmProviders: LLMProviderDescriptor[] | undefined,
  currentModelName?: string
): LLMOption[] {
  if (!llmProviders) {
    return [];
  }

  // Track seen combinations of provider + exact model name to avoid true duplicates
  // (same model appearing from multiple LLM provider configs with same provider type)
  const seenKeys = new Set<string>();
  const options: LLMOption[] = [];

  llmProviders.forEach((llmProvider) => {
    llmProvider.model_configurations
      .filter(
        (modelConfiguration) =>
          modelConfiguration.is_visible ||
          modelConfiguration.name === currentModelName
      )
      .forEach((modelConfiguration) => {
        // Deduplicate by exact provider + model name combination
        const key = `${llmProvider.provider}:${modelConfiguration.name}`;
        if (seenKeys.has(key)) {
          return;
        }
        seenKeys.add(key);

        options.push({
          name: llmProvider.name,
          provider: llmProvider.provider,
          providerDisplayName:
            llmProvider.provider_display_name || llmProvider.provider,
          modelName: modelConfiguration.name,
          displayName:
            modelConfiguration.display_name || modelConfiguration.name,
          vendor: modelConfiguration.vendor || null,
          maxInputTokens: modelConfiguration.max_input_tokens,
          region: modelConfiguration.region || null,
          version: modelConfiguration.version || null,
          supportsReasoning: modelConfiguration.supports_reasoning || false,
          supportsImageInput: modelConfiguration.supports_image_input || false,
        });
      });
  });

  return options;
}

export function groupLlmOptions(
  filteredOptions: LLMOption[]
): LLMOptionGroup[] {
  const groups = new Map<string, Omit<LLMOptionGroup, "key">>();

  filteredOptions.forEach((option) => {
    const provider = option.provider.toLowerCase();
    const isAggregator = AGGREGATOR_PROVIDERS.has(provider);
    const groupKey =
      isAggregator && option.vendor
        ? `${provider}/${option.vendor.toLowerCase()}`
        : provider;

    if (!groups.has(groupKey)) {
      let displayName: string;

      if (isAggregator && option.vendor) {
        const vendorDisplayName =
          option.vendor.charAt(0).toUpperCase() + option.vendor.slice(1);
        displayName = `${option.providerDisplayName}/${vendorDisplayName}`;
      } else {
        displayName = option.providerDisplayName;
      }

      groups.set(groupKey, {
        displayName,
        options: [],
        Icon: getProviderIcon(provider),
      });
    }

    groups.get(groupKey)!.options.push(option);
  });

  const sortedKeys = Array.from(groups.keys()).sort((a, b) =>
    groups.get(a)!.displayName.localeCompare(groups.get(b)!.displayName)
  );

  return sortedKeys.map((key) => {
    const group = groups.get(key)!;
    return {
      key,
      displayName: group.displayName,
      options: group.options,
      Icon: group.Icon,
    };
  });
}

export default function LLMPopover({
  llmManager,
  requiresImageInput,
  foldable,
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

  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const handleGlobalTemperatureChange = useCallback((value: number[]) => {
    const value_0 = value[0];
    if (value_0 !== undefined) {
      setLocalTemperature(value_0);
    }
  }, []);

  const handleGlobalTemperatureCommit = useCallback(
    (value: number[]) => {
      const value_0 = value[0];
      if (value_0 !== undefined) {
        llmManager.updateTemperature(value_0);
      }
    },
    [llmManager]
  );

  const isSelected = useCallback(
    (option: LLMOption) =>
      option.modelName === llmManager.currentLlm.modelName &&
      option.provider === llmManager.currentLlm.provider,
    [llmManager.currentLlm.modelName, llmManager.currentLlm.provider]
  );

  const handleSelectModel = useCallback(
    (option: LLMOption) => {
      llmManager.updateCurrentLlm({
        modelName: option.modelName,
        provider: option.provider,
        name: option.name,
      } as LlmDescriptor);
      onSelect?.(
        structureValue(option.name, option.provider, option.modelName)
      );
      setOpen(false);
    },
    [llmManager, onSelect]
  );

  const currentLlmDisplayName = useMemo(() => {
    // Only use currentModelName if it's a non-empty string
    const currentModel =
      currentModelName && currentModelName.trim()
        ? currentModelName
        : llmManager.currentLlm.modelName;
    if (!llmProviders) return currentModel;

    for (const provider of llmProviders) {
      const config = provider.model_configurations.find(
        (m) => m.name === currentModel
      );
      if (config) {
        return config.display_name || config.name;
      }
    }
    return currentModel;
  }, [llmProviders, currentModelName, llmManager.currentLlm.modelName]);

  const temperatureFooter = user?.preferences?.temperature_override_enabled ? (
    <>
      <div className="border-t border-border-02 mx-2" />
      <div className="flex flex-col w-full py-2 gap-2">
        <Slider
          value={[localTemperature]}
          max={llmManager.maxTemperature}
          min={0}
          step={0.01}
          onValueChange={handleGlobalTemperatureChange}
          onValueCommit={handleGlobalTemperatureCommit}
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
    <Popover open={open} onOpenChange={setOpen}>
      <div data-testid="llm-popover-trigger">
        <Popover.Trigger asChild disabled={disabled}>
          <OpenButton
            disabled={disabled}
            icon={
              foldable
                ? SvgRefreshCw
                : getProviderIcon(
                    llmManager.currentLlm.provider,
                    llmManager.currentLlm.modelName
                  )
            }
            foldable={foldable}
          >
            {currentLlmDisplayName}
          </OpenButton>
        </Popover.Trigger>
      </div>

      <Popover.Content side="top" align="end" width="xl">
        <ModelListContent
          llmProviders={llmProviders}
          currentModelName={currentModelName}
          requiresImageInput={requiresImageInput}
          isLoading={isLoadingProviders}
          onSelect={handleSelectModel}
          isSelected={isSelected}
          scrollContainerRef={scrollContainerRef}
          footer={temperatureFooter}
        />
      </Popover.Content>
    </Popover>
  );
}
