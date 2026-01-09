"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
  PopoverMenu,
} from "@/components/ui/popover";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { structureValue } from "@/lib/llm/utils";
import {
  getProviderIcon,
  AGGREGATOR_PROVIDERS,
} from "@/app/admin/configuration/llm/utils";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import LineItem from "@/refresh-components/buttons/LineItem";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  SvgCheck,
  SvgChevronDown,
  SvgChevronRight,
  SvgSliders,
  SvgX,
} from "@opal/icons";
import { IconProps } from "@/components/icons/icons";
import Checkbox from "@/refresh-components/inputs/Checkbox";

interface LLMOption {
  name: string;
  provider: string;
  providerDisplayName: string;
  modelName: string;
  displayName: string;
  description?: string;
  vendor: string | null;
  maxInputTokens?: number | null;
  region?: string | null;
  version?: string | null;
  supportsReasoning?: boolean;
  supportsImageInput?: boolean;
}

export interface MultiModelSelectorProps {
  llmManager: LlmManager;
  selectedModels: LlmDescriptor[];
  onModelsChange: (models: LlmDescriptor[]) => void;
  maxModels?: number;
  disabled?: boolean;
}

export default function MultiModelSelector({
  llmManager,
  selectedModels,
  onModelsChange,
  maxModels = 3,
  disabled = false,
}: MultiModelSelectorProps) {
  const llmProviders = llmManager.llmProviders;
  const isLoadingProviders = llmManager.isLoadingProviders;

  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const searchInputRef = useRef<HTMLInputElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const llmOptions = useMemo(() => {
    if (!llmProviders) {
      return [];
    }

    const seenKeys = new Set<string>();
    const options: LLMOption[] = [];

    llmProviders.forEach((llmProvider) => {
      llmProvider.model_configurations
        .filter((modelConfiguration) => modelConfiguration.is_visible)
        .forEach((modelConfiguration) => {
          const key = `${llmProvider.provider}:${modelConfiguration.name}`;

          if (seenKeys.has(key)) {
            return;
          }
          seenKeys.add(key);

          const displayName =
            modelConfiguration.display_name || modelConfiguration.name;

          options.push({
            name: llmProvider.name,
            provider: llmProvider.provider,
            providerDisplayName:
              llmProvider.provider_display_name || llmProvider.provider,
            modelName: modelConfiguration.name,
            displayName,
            vendor: modelConfiguration.vendor || null,
            maxInputTokens: modelConfiguration.max_input_tokens,
            region: modelConfiguration.region || null,
            version: modelConfiguration.version || null,
            supportsReasoning: modelConfiguration.supports_reasoning || false,
            supportsImageInput:
              modelConfiguration.supports_image_input || false,
          });
        });
    });

    return options;
  }, [llmProviders]);

  const filteredOptions = useMemo(() => {
    if (!searchQuery.trim()) {
      return llmOptions;
    }
    const query = searchQuery.toLowerCase();
    return llmOptions.filter(
      (opt) =>
        opt.displayName.toLowerCase().includes(query) ||
        opt.modelName.toLowerCase().includes(query) ||
        (opt.vendor && opt.vendor.toLowerCase().includes(query))
    );
  }, [llmOptions, searchQuery]);

  const groupedOptions = useMemo(() => {
    const groups = new Map<
      string,
      {
        displayName: string;
        options: LLMOption[];
        Icon: React.FunctionComponent<IconProps>;
      }
    >();

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
  }, [filteredOptions]);

  const [expandedGroups, setExpandedGroups] = useState<string[]>([]);

  useEffect(() => {
    if (!open) {
      setSearchQuery("");
    } else {
      // Expand all groups by default when opening
      setExpandedGroups(groupedOptions.map((g) => g.key));
    }
  }, [open, groupedOptions]);

  const isSearching = searchQuery.trim().length > 0;

  const effectiveExpandedGroups = useMemo(() => {
    if (isSearching) {
      return groupedOptions.map((g) => g.key);
    }
    return expandedGroups;
  }, [isSearching, groupedOptions, expandedGroups]);

  const handleAccordionChange = (value: string[]) => {
    if (!isSearching) {
      setExpandedGroups(value);
    }
  };

  const isModelSelected = (option: LLMOption) => {
    return selectedModels.some(
      (m) => m.modelName === option.modelName && m.provider === option.provider
    );
  };

  const handleToggleModel = (option: LLMOption) => {
    const isSelected = isModelSelected(option);

    if (isSelected) {
      // Remove model
      const newModels = selectedModels.filter(
        (m) =>
          !(m.modelName === option.modelName && m.provider === option.provider)
      );
      onModelsChange(newModels);
    } else {
      // Add model if under max
      if (selectedModels.length < maxModels) {
        const newModel: LlmDescriptor = {
          name: option.name,
          modelName: option.modelName,
          provider: option.provider,
        };
        onModelsChange([...selectedModels, newModel]);
      }
    }
  };

  const handleClearAll = () => {
    onModelsChange([]);
  };

  const renderModelItem = (option: LLMOption) => {
    const isSelected = isModelSelected(option);
    const canSelect = selectedModels.length < maxModels || isSelected;

    const capabilities: string[] = [];
    if (option.supportsReasoning) {
      capabilities.push("Reasoning");
    }
    if (option.supportsImageInput) {
      capabilities.push("Vision");
    }
    const description =
      capabilities.length > 0 ? capabilities.join(", ") : undefined;

    return (
      <div key={`${option.name}-${option.modelName}`}>
        <LineItem
          selected={isSelected}
          description={description}
          onClick={() => canSelect && handleToggleModel(option)}
          icon={() => null}
          rightChildren={
            <Checkbox
              checked={isSelected}
              disabled={!canSelect}
              onCheckedChange={() => canSelect && handleToggleModel(option)}
            />
          }
          className={!canSelect ? "opacity-50 cursor-not-allowed" : ""}
        >
          {option.displayName}
        </LineItem>
      </div>
    );
  };

  const buttonLabel = useMemo(() => {
    if (selectedModels.length === 0) {
      return "Select models";
    }
    return `${selectedModels.length}/${maxModels} models`;
  }, [selectedModels.length, maxModels]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild disabled={disabled}>
        <div data-testid="multi-model-selector-trigger">
          <SelectButton
            leftIcon={SvgSliders}
            onClick={() => setOpen(true)}
            transient={open}
            rightChevronIcon
            disabled={disabled}
            className={disabled ? "bg-transparent" : ""}
          >
            {buttonLabel}
          </SelectButton>
        </div>
      </PopoverTrigger>
      <PopoverContent side="top" align="end" className="w-[320px] p-1.5">
        <div className="flex flex-col gap-2">
          {/* Header with count and clear button */}
          <div className="flex items-center justify-between px-2 py-1">
            <Text secondaryBody text03>
              Select up to {maxModels} models
            </Text>
            {selectedModels.length > 0 && (
              <button
                onClick={handleClearAll}
                className="flex items-center gap-1 text-xs text-text-04 hover:text-text-01"
              >
                <SvgX className="h-3 w-3" />
                Clear
              </button>
            )}
          </div>

          {/* Selected models display */}
          {selectedModels.length > 0 && (
            <div className="flex flex-wrap gap-1 px-2">
              {selectedModels.map((model, idx) => {
                const option = llmOptions.find(
                  (o) =>
                    o.modelName === model.modelName &&
                    o.provider === model.provider
                );
                return (
                  <div
                    key={`selected-${idx}`}
                    className="flex items-center gap-1 px-2 py-1 bg-background-neutral-01 rounded-08 text-xs"
                  >
                    <span className="text-text-01">
                      {option?.displayName || model.modelName}
                    </span>
                    <button
                      onClick={() =>
                        handleToggleModel(
                          option ||
                            ({
                              modelName: model.modelName,
                              provider: model.provider,
                              name: model.name,
                            } as LLMOption)
                        )
                      }
                      className="text-text-04 hover:text-text-01"
                    >
                      <SvgX className="h-3 w-3" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {/* Search Input */}
          <InputTypeIn
            ref={searchInputRef}
            leftSearchIcon
            internal
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search models..."
          />

          {/* Model List with Vendor Groups */}
          <PopoverMenu
            scrollContainerRef={scrollContainerRef}
            className="w-full max-h-[20rem]"
          >
            {isLoadingProviders
              ? [
                  <div
                    key="loading"
                    className="flex items-center gap-2 px-2 py-3"
                  >
                    <SimpleLoader />
                    <Text secondaryBody text03>
                      Loading models...
                    </Text>
                  </div>,
                ]
              : groupedOptions.length === 0
                ? [
                    <div key="empty" className="px-2 py-3">
                      <Text secondaryBody text03>
                        No models found
                      </Text>
                    </div>,
                  ]
                : groupedOptions.length === 1
                  ? [
                      <div
                        key="single-provider"
                        className="flex flex-col gap-1"
                      >
                        {groupedOptions[0]!.options.map(renderModelItem)}
                      </div>,
                    ]
                  : [
                      <Accordion
                        key="accordion"
                        type="multiple"
                        value={effectiveExpandedGroups}
                        onValueChange={handleAccordionChange}
                        className="w-full flex flex-col"
                      >
                        {groupedOptions.map((group) => {
                          const isExpanded = effectiveExpandedGroups.includes(
                            group.key
                          );
                          return (
                            <AccordionItem
                              key={group.key}
                              value={group.key}
                              className="border-none pt-1"
                            >
                              <AccordionTrigger className="flex items-center rounded-08 hover:no-underline hover:bg-background-tint-02 group [&>svg]:hidden w-full py-1 px-1.5">
                                <div className="flex items-center gap-1 shrink-0">
                                  <div className="flex items-center justify-center size-5 shrink-0">
                                    <group.Icon size={16} />
                                  </div>
                                  <Text
                                    secondaryBody
                                    text03
                                    nowrap
                                    className="px-0.5"
                                  >
                                    {group.displayName}
                                  </Text>
                                </div>
                                <div className="flex-1" />
                                <div className="flex items-center justify-center size-6 shrink-0">
                                  {isExpanded ? (
                                    <SvgChevronDown className="h-4 w-4 stroke-text-04 shrink-0" />
                                  ) : (
                                    <SvgChevronRight className="h-4 w-4 stroke-text-04 shrink-0" />
                                  )}
                                </div>
                              </AccordionTrigger>

                              <AccordionContent className="pb-0 pt-0">
                                <div className="flex flex-col gap-1">
                                  {group.options.map(renderModelItem)}
                                </div>
                              </AccordionContent>
                            </AccordionItem>
                          );
                        })}
                      </Accordion>,
                    ]}
          </PopoverMenu>
        </div>
      </PopoverContent>
    </Popover>
  );
}
