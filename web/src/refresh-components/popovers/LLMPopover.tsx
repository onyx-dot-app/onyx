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
import { Slider } from "@/components/ui/slider";
import { useUser } from "@/components/user/UserProvider";
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
  SvgRefreshCw,
} from "@opal/icons";
import { IconProps } from "@/components/icons/icons";

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
  folded,
  onSelect,
  currentModelName,
  disabled = false,
}: LLMPopoverProps) {
  const llmProviders = llmManager.llmProviders;
  const isLoadingProviders = llmManager.isLoadingProviders;

  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const { user } = useUser();

  const [localTemperature, setLocalTemperature] = useState(
    llmManager.temperature ?? 0.5
  );

  useEffect(() => {
    setLocalTemperature(llmManager.temperature ?? 0.5);
  }, [llmManager.temperature]);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const selectedItemRef = useRef<HTMLDivElement>(null);

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

  const llmOptions = useMemo(() => {
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
  }, [llmProviders, currentModelName]);

  // Filter options by search query
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

  // Group options by provider using backend-provided display names and ordering
  // For aggregator providers (bedrock, openrouter, vertex_ai), flatten to "Provider/Vendor" format
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

      // For aggregator providers with vendor info, create flattened groups like "Amazon Bedrock/Anthropic"
      // For regular providers or aggregators without vendor, use just the provider name
      const groupKey =
        isAggregator && option.vendor
          ? `${provider}/${option.vendor.toLowerCase()}`
          : provider;

      if (!groups.has(groupKey)) {
        // Build display name
        let displayName: string;

        if (isAggregator && option.vendor) {
          // Flattened format: "Amazon Bedrock/Anthropic"
          const vendorDisplayName =
            option.vendor.charAt(0).toUpperCase() + option.vendor.slice(1);
          displayName = `${option.providerDisplayName}/${vendorDisplayName}`;
        } else {
          displayName = option.providerDisplayName;
        }

        groups.set(groupKey, {
          displayName,
          options: [],
          // Get the icon component - use provider for the icon lookup
          Icon: getProviderIcon(provider),
        });
      }

      groups.get(groupKey)!.options.push(option);
    });

    // Sort groups alphabetically by display name
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

  // Get display name for the model to show in the button
  // Use currentModelName prop if provided (e.g., for regenerate showing the model used),
  // otherwise fall back to the globally selected model
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

  // Determine which group the current model belongs to (for auto-expand)
  const currentGroupKey = useMemo(() => {
    const currentModel = llmManager.currentLlm.modelName;
    const currentProvider = llmManager.currentLlm.provider;
    // Match by both modelName AND provider to handle same model name across providers
    const option = llmOptions.find(
      (o) => o.modelName === currentModel && o.provider === currentProvider
    );
    if (!option) return "openai";

    const provider = option.provider.toLowerCase();
    const isAggregator = AGGREGATOR_PROVIDERS.has(provider);

    if (isAggregator && option.vendor) {
      return `${provider}/${option.vendor.toLowerCase()}`;
    }
    return provider;
  }, [
    llmOptions,
    llmManager.currentLlm.modelName,
    llmManager.currentLlm.provider,
  ]);

  // Track expanded groups - initialize with current model's group
  const [expandedGroups, setExpandedGroups] = useState<string[]>([
    currentGroupKey,
  ]);

  // Reset state when popover closes/opens
  useEffect(() => {
    if (!open) {
      setSearchQuery("");
    } else {
      // Reset expanded groups to only show the selected model's group
      setExpandedGroups([currentGroupKey]);
    }
  }, [open, currentGroupKey]);

  // Auto-scroll to selected model when popover opens
  useEffect(() => {
    if (open) {
      // Small delay to let accordion content render
      const timer = setTimeout(() => {
        selectedItemRef.current?.scrollIntoView({
          behavior: "instant",
          block: "center",
        });
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [open]);

  const isSearching = searchQuery.trim().length > 0;

  // Compute final expanded groups
  const effectiveExpandedGroups = useMemo(() => {
    if (isSearching) {
      // Force expand all when searching
      return groupedOptions.map((g) => g.key);
    }
    return expandedGroups;
  }, [isSearching, groupedOptions, expandedGroups]);

  // Handler for accordion changes
  const handleAccordionChange = (value: string[]) => {
    // Only update state when not searching (force-expanding)
    if (!isSearching) {
      setExpandedGroups(value);
    }
  };

  const handleSelectModel = (option: LLMOption) => {
    llmManager.updateCurrentLlm({
      modelName: option.modelName,
      provider: option.provider,
      name: option.name,
    } as LlmDescriptor);
    onSelect?.(structureValue(option.name, option.provider, option.modelName));
    setOpen(false);
  };

  const renderModelItem = (option: LLMOption) => {
    const isSelected =
      option.modelName === llmManager.currentLlm.modelName &&
      option.provider === llmManager.currentLlm.provider;

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
      <div
        key={`${option.name}-${option.modelName}`}
        ref={isSelected ? selectedItemRef : undefined}
      >
        <LineItem
          selected={isSelected}
          description={description}
          onClick={() => handleSelectModel(option)}
          icon={() => null}
          rightChildren={
            isSelected ? (
              <SvgCheck className="h-4 w-4 stroke-action-link-05 shrink-0" />
            ) : null
          }
        >
          {option.displayName}
        </LineItem>
      </div>
    );
  };

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
            {currentLlmDisplayName}
          </SelectButton>
        </div>
      </PopoverTrigger>
      <PopoverContent side="top" align="end" className="w-[280px] p-1.5">
        <div className="flex flex-col gap-2">
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
            className="w-full max-h-[22.5rem]"
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
                  ? // Single provider - show models directly without accordion
                    [
                      <div
                        key="single-provider"
                        className="flex flex-col gap-1"
                      >
                        {groupedOptions[0]!.options.map(renderModelItem)}
                      </div>,
                    ]
                  : // Multiple providers - show accordion with groups
                    [
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
                              {/* Group Header */}
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

                              {/* Model Items - full width highlight */}
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

          {/* Global Temperature Slider (shown if enabled in user prefs) */}
          {user?.preferences?.temperature_override_enabled && (
            <>
              <div className="border-t border-border-02 mx-2" />
              <div className="flex flex-col w-full py-2 px-2 gap-2">
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
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
