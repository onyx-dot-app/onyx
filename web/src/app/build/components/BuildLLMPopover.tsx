"use client";

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import {
  SvgCheck,
  SvgChevronDown,
  SvgChevronRight,
  SvgPlug,
} from "@opal/icons";
import Text from "@/refresh-components/texts/Text";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import Switch from "@/refresh-components/inputs/Switch";
import LineItem from "@/refresh-components/buttons/LineItem";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import {
  BuildLlmSelection,
  BUILD_MODE_PROVIDERS,
  isRecommendedModel,
} from "@/app/build/onboarding/constants";
import { ToggleWarningModal } from "./ToggleWarningModal";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import { Section } from "@/layouts/general-layouts";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

interface BuildLLMPopoverProps {
  currentSelection: BuildLlmSelection | null;
  onSelectionChange: (selection: BuildLlmSelection) => void;
  llmProviders: LLMProviderDescriptor[] | undefined;
  onOpenOnboarding: (providerKey: string) => void;
  children: React.ReactNode;
  disabled?: boolean;
}

interface ModelOption {
  providerKey: string;
  providerName: string;
  providerDisplayName: string;
  modelName: string;
  displayName: string;
  isRecommended: boolean;
  isConfigured: boolean;
}

export function BuildLLMPopover({
  currentSelection,
  onSelectionChange,
  llmProviders,
  onOpenOnboarding,
  children,
  disabled = false,
}: BuildLLMPopoverProps) {
  const [showRecommendedOnly, setShowRecommendedOnly] = useState(true);
  const [showToggleWarning, setShowToggleWarning] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const isClosingModalRef = useRef(false);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const selectedItemRef = useRef<HTMLDivElement>(null);

  // Check which providers are configured (exact match on provider field)
  const isProviderConfigured = useCallback(
    (providerKey: string) => {
      return llmProviders?.some((p) => p.provider === providerKey);
    },
    [llmProviders]
  );

  // Get the actual provider descriptor for a configured provider
  const getProviderDescriptor = useCallback(
    (providerKey: string) => {
      return llmProviders?.find((p) => p.provider === providerKey);
    },
    [llmProviders]
  );

  // Build model options based on mode
  const modelOptions = useMemo((): ModelOption[] => {
    const options: ModelOption[] = [];

    if (showRecommendedOnly) {
      // Show curated list from BUILD_MODE_PROVIDERS
      BUILD_MODE_PROVIDERS.forEach((provider) => {
        const isConfigured = isProviderConfigured(provider.providerName);
        const descriptor = getProviderDescriptor(provider.providerName);
        const modelsToShow = provider.models.filter((m) => m.recommended);

        modelsToShow.forEach((model) => {
          // Get display name from backend if available
          const backendConfig = descriptor?.model_configurations.find(
            (mc) => mc.name === model.name
          );
          options.push({
            providerKey: provider.providerName,
            providerName: descriptor?.name || provider.label,
            providerDisplayName: provider.label,
            modelName: model.name,
            displayName: backendConfig?.display_name || model.label,
            isRecommended: true,
            isConfigured: isConfigured ?? false,
          });
        });
      });
    } else {
      // Show ALL configured providers and their visible models
      llmProviders?.forEach((provider) => {
        const visibleModels = provider.model_configurations.filter(
          (m) => m.is_visible
        );

        visibleModels.forEach((model) => {
          options.push({
            providerKey: provider.provider,
            providerName: provider.name,
            providerDisplayName:
              provider.provider_display_name || provider.provider,
            modelName: model.name,
            displayName: model.display_name || model.name,
            isRecommended: isRecommendedModel(provider.provider, model.name),
            isConfigured: true,
          });
        });
      });
    }

    return options;
  }, [
    showRecommendedOnly,
    llmProviders,
    isProviderConfigured,
    getProviderDescriptor,
  ]);

  // Group options by provider
  const groupedOptions = useMemo(() => {
    const groups = new Map<
      string,
      {
        providerKey: string;
        displayName: string;
        options: ModelOption[];
        isConfigured: boolean;
      }
    >();

    modelOptions.forEach((option) => {
      const groupKey = option.providerKey;

      if (!groups.has(groupKey)) {
        groups.set(groupKey, {
          providerKey: option.providerKey,
          displayName: option.providerDisplayName,
          options: [],
          isConfigured: option.isConfigured,
        });
      }

      groups.get(groupKey)!.options.push(option);
    });

    // Sort groups alphabetically
    const sortedKeys = Array.from(groups.keys()).sort((a, b) =>
      groups.get(a)!.displayName.localeCompare(groups.get(b)!.displayName)
    );

    return sortedKeys.map((key) => groups.get(key)!);
  }, [modelOptions]);

  // Determine current group for auto-expand
  const currentGroupKey = useMemo(() => {
    if (!currentSelection) return "";
    return currentSelection.provider;
  }, [currentSelection]);

  // Track expanded groups
  const [expandedGroups, setExpandedGroups] = useState<string[]>([
    currentGroupKey,
  ]);

  // Reset expanded groups when popover opens
  useEffect(() => {
    if (isOpen) {
      setExpandedGroups([currentGroupKey]);
    }
  }, [isOpen, currentGroupKey]);

  // Auto-scroll to selected model
  useEffect(() => {
    if (isOpen) {
      const timer = setTimeout(() => {
        selectedItemRef.current?.scrollIntoView({
          behavior: "instant",
          block: "center",
        });
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [isOpen]);

  const handleAccordionChange = (value: string[]) => {
    setExpandedGroups(value);
  };

  const applySelection = useCallback(
    (option: ModelOption) => {
      if (!option.isConfigured) return;

      onSelectionChange({
        providerName: option.providerName,
        provider: option.providerKey,
        modelName: option.modelName,
      });
      setIsOpen(false);
    },
    [onSelectionChange]
  );

  // Handle toggle change - show warning when turning OFF
  const handleToggleChange = (checked: boolean) => {
    if (!checked && showRecommendedOnly) {
      setShowToggleWarning(true);
    } else {
      setShowRecommendedOnly(checked);
    }
  };

  // Reset closing flag after modal close transition
  useEffect(() => {
    if (!showToggleWarning && isClosingModalRef.current) {
      const timeoutId = setTimeout(() => {
        isClosingModalRef.current = false;
      }, 100);
      return () => clearTimeout(timeoutId);
    }
  }, [showToggleWarning]);

  const handleConnectClick = (providerKey: string) => {
    setIsOpen(false);
    onOpenOnboarding(providerKey);
  };

  const handlePopoverOpenChange = (open: boolean) => {
    if (disabled && open) {
      return;
    }
    if (!open && (showToggleWarning || isClosingModalRef.current)) {
      return;
    }
    setIsOpen(open);
  };

  const renderModelItem = (option: ModelOption) => {
    const isSelected =
      currentSelection?.modelName === option.modelName &&
      currentSelection?.provider === option.providerKey;

    // Build description with recommendation badge
    const description = option.isRecommended ? "Recommended" : undefined;

    return (
      <div
        key={`${option.providerKey}-${option.modelName}`}
        ref={isSelected ? selectedItemRef : undefined}
      >
        <LineItem
          selected={isSelected}
          description={description}
          onClick={() => applySelection(option)}
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
    <>
      <Popover open={isOpen} onOpenChange={handlePopoverOpenChange}>
        <Popover.Trigger asChild>{children}</Popover.Trigger>
        <Popover.Content
          side="bottom"
          align="start"
          width="lg"
          onInteractOutside={(e) => {
            if (showToggleWarning || isClosingModalRef.current) {
              e.preventDefault();
            }
          }}
          onPointerDownOutside={(e) => {
            if (showToggleWarning || isClosingModalRef.current) {
              e.preventDefault();
            }
          }}
        >
          <div className="px-3">
            <Section gap={0.5}>
              {/* Toggle for recommended only */}
              <div className="flex items-center justify-between py-3 gap-3 border-b border-border-01 px-1">
                <Text secondaryBody text03>
                  Recommended Models Only
                </Text>
                <Switch
                  checked={showRecommendedOnly}
                  onCheckedChange={handleToggleChange}
                />
              </div>

              {/* Model List */}
              <PopoverMenu scrollContainerRef={scrollContainerRef}>
                {groupedOptions.length === 0
                  ? [
                      <div key="empty" className="py-3 px-2">
                        <Text secondaryBody text03>
                          No models found
                        </Text>
                      </div>,
                    ]
                  : groupedOptions.length === 1
                    ? // Single provider - show models directly
                      [
                        <div
                          key="single-provider"
                          className="flex flex-col gap-1"
                        >
                          {groupedOptions[0]!.isConfigured ? (
                            groupedOptions[0]!.options.map(renderModelItem)
                          ) : (
                            <div className="flex items-center justify-between px-2 py-2">
                              <Text secondaryBody text03>
                                Not configured
                              </Text>
                              <button
                                onClick={() =>
                                  handleConnectClick(
                                    groupedOptions[0]!.providerKey
                                  )
                                }
                                className="flex items-center gap-1 px-2 py-1 text-xs rounded-08 bg-background-02 hover:bg-background-03 transition-colors"
                              >
                                <SvgPlug className="w-3 h-3" />
                                <span>Connect</span>
                              </button>
                            </div>
                          )}
                        </div>,
                      ]
                    : // Multiple providers - show accordion
                      [
                        <Accordion
                          key="accordion"
                          type="multiple"
                          value={expandedGroups}
                          onValueChange={handleAccordionChange}
                          className="w-full flex flex-col"
                        >
                          {groupedOptions.map((group) => {
                            const isExpanded = expandedGroups.includes(
                              group.providerKey
                            );
                            const ProviderIcon = getProviderIcon(
                              group.providerKey
                            );

                            return (
                              <AccordionItem
                                key={group.providerKey}
                                value={group.providerKey}
                                className="border-none pt-1"
                              >
                                {/* Group Header */}
                                <AccordionTrigger className="flex items-center rounded-08 hover:no-underline hover:bg-background-tint-02 group [&>svg]:hidden w-full py-1">
                                  <div className="flex items-center gap-1 shrink-0">
                                    <div className="flex items-center justify-center size-5 shrink-0">
                                      <ProviderIcon size={16} />
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
                                  {!group.isConfigured && (
                                    <button
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        handleConnectClick(group.providerKey);
                                      }}
                                      className="flex items-center gap-1 px-2 py-0.5 mr-1 text-xs rounded-08 bg-background-02 hover:bg-background-03 transition-colors"
                                    >
                                      <SvgPlug className="w-3 h-3" />
                                      <span>Connect</span>
                                    </button>
                                  )}
                                  <div className="flex items-center justify-center size-6 shrink-0">
                                    {isExpanded ? (
                                      <SvgChevronDown className="h-4 w-4 stroke-text-04 shrink-0" />
                                    ) : (
                                      <SvgChevronRight className="h-4 w-4 stroke-text-04 shrink-0" />
                                    )}
                                  </div>
                                </AccordionTrigger>

                                {/* Model Items */}
                                <AccordionContent className="pb-0 pt-0">
                                  <div className="flex flex-col gap-1">
                                    {group.isConfigured ? (
                                      group.options.map(renderModelItem)
                                    ) : (
                                      <div className="py-1.5 px-3">
                                        <Text secondaryBody text03>
                                          Not configured
                                        </Text>
                                      </div>
                                    )}
                                  </div>
                                </AccordionContent>
                              </AccordionItem>
                            );
                          })}
                        </Accordion>,
                      ]}
              </PopoverMenu>
            </Section>
          </div>
        </Popover.Content>
      </Popover>

      {/* Warning modal when turning OFF "Recommended Models Only" */}
      <ToggleWarningModal
        open={showToggleWarning}
        onConfirm={() => {
          setShowRecommendedOnly(false);
          isClosingModalRef.current = true;
          setShowToggleWarning(false);
        }}
        onCancel={() => {
          isClosingModalRef.current = true;
          setShowToggleWarning(false);
        }}
      />
    </>
  );
}
