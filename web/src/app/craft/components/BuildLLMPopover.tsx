"use client";

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { SvgCheck, SvgChevronDown, SvgChevronRight } from "@opal/icons";
import { Text, Popover, PopoverMenu, LineItemButton } from "@opal/components";
import { Switch } from "@opal/components";
import {
  LLMProviderDescriptor,
  ModelConfiguration,
} from "@/lib/languageModels/types";
import {
  BuildLlmSelection,
  craftProviderDisplayName,
  isCraftRecommendedModel,
} from "@/app/craft/onboarding/constants";
import {
  getStoredRecommendedModelsOnly,
  setStoredLlmSelection,
  setStoredRecommendedModelsOnly,
} from "@/app/craft/utils/llmPreferences";
import { useUser } from "@/providers/UserProvider";
import { getModelIcon } from "@/lib/languageModels";
import { AGGREGATOR_PROVIDERS } from "@/lib/languageModels/svc";
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
  children: React.ReactNode;
  disabled?: boolean;
  // Admin surfaces that edit a workspace-wide setting pass `false` so the
  // admin's own remembered pick isn't overwritten by that edit.
  persistSelection?: boolean;
}

interface ModelOption {
  providerId: number;
  providerKey: string;
  groupKey: string;
  providerName: string;
  groupDisplayName: string;
  modelName: string;
  displayName: string;
  isRecommended: boolean;
}

function modelDisplayName(model: ModelConfiguration): string {
  return model.effectiveDisplayName || model.display_name || model.name;
}

// Keyed by provider id, unlike the main app's `groupLlmOptions`, so two
// providers sharing a display name stay distinct.
function craftGroupKey(
  providerId: number,
  providerKey: string,
  vendor: string | null
): string {
  return AGGREGATOR_PROVIDERS.has(providerKey.toLowerCase()) && vendor
    ? `${providerId}/${vendor.toLowerCase()}`
    : String(providerId);
}

export function BuildLLMPopover({
  currentSelection,
  onSelectionChange,
  llmProviders,
  children,
  disabled = false,
  persistSelection = true,
}: BuildLLMPopoverProps) {
  const { user } = useUser();
  const userId = user?.id;
  // Storage is the source of truth for the toggle (the user id it's keyed by
  // loads asynchronously, so derive at render); state only tracks an
  // in-session flip, which also writes through to storage.
  const [recommendedOnlyFlip, setRecommendedOnlyFlip] = useState<
    boolean | null
  >(null);
  const showRecommendedOnly =
    recommendedOnlyFlip ?? getStoredRecommendedModelsOnly(userId);
  const [isOpen, setIsOpen] = useState(false);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const selectedItemRef = useRef<HTMLDivElement>(null);

  // Build model options based on mode
  const modelOptions = useMemo((): ModelOption[] => {
    const options: ModelOption[] = [];

    llmProviders?.forEach((provider) => {
      // Recommended-only still lists the active model so the current pick
      // (e.g. restored from a stored preference) is never invisible.
      const isCurrent = (model: ModelConfiguration): boolean =>
        currentSelection?.providerId === provider.id &&
        currentSelection.modelName === model.name;
      const models = showRecommendedOnly
        ? provider.model_configurations.filter(
            (model) =>
              model.is_visible &&
              (isCraftRecommendedModel(model) || isCurrent(model))
          )
        : provider.model_configurations.filter((model) => model.is_visible);
      const providerDisplayName = craftProviderDisplayName(provider);
      models.forEach((model) => {
        const vendor = model.vendor || null;
        const groupKey = craftGroupKey(provider.id, provider.provider, vendor);
        options.push({
          providerId: provider.id,
          providerKey: provider.provider,
          groupKey,
          providerName: provider.name ?? "",
          groupDisplayName:
            groupKey === String(provider.id)
              ? providerDisplayName
              : `${providerDisplayName}/${vendor}`,
          modelName: model.name,
          displayName: modelDisplayName(model),
          isRecommended: isCraftRecommendedModel(model),
        });
      });
    });

    return options;
  }, [showRecommendedOnly, llmProviders, currentSelection]);

  // Group options by provider
  const groupedOptions = useMemo(() => {
    const groups = new Map<
      string,
      {
        groupKey: string;
        providerKey: string;
        displayName: string;
        options: ModelOption[];
      }
    >();

    modelOptions.forEach((option) => {
      const groupKey = option.groupKey;

      if (!groups.has(groupKey)) {
        groups.set(groupKey, {
          groupKey,
          providerKey: option.providerKey,
          displayName: option.groupDisplayName,
          options: [],
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
    const provider = llmProviders?.find(
      (candidate) => candidate.id === currentSelection.providerId
    );
    const vendor =
      provider?.model_configurations.find(
        (model) => model.name === currentSelection.modelName
      )?.vendor || null;
    // Must use the same slug source as the group keys above; a persisted
    // selection can carry a stale one.
    return craftGroupKey(
      currentSelection.providerId,
      provider?.provider ?? currentSelection.provider,
      vendor
    );
  }, [currentSelection, llmProviders]);

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

  const handleRecommendedOnlyChange = useCallback(
    (checked: boolean) => {
      setRecommendedOnlyFlip(checked);
      setStoredRecommendedModelsOnly(userId, checked);
    },
    [userId]
  );

  const applySelection = useCallback(
    (option: ModelOption) => {
      const selection: BuildLlmSelection = {
        providerId: option.providerId,
        providerName: option.providerName,
        provider: option.providerKey,
        modelName: option.modelName,
      };
      if (persistSelection) setStoredLlmSelection(userId, selection);
      onSelectionChange(selection);
      setIsOpen(false);
    },
    [userId, persistSelection, onSelectionChange]
  );

  const handlePopoverOpenChange = (open: boolean) => {
    if (disabled && open) {
      return;
    }
    setIsOpen(open);
  };

  const renderModelItem = (option: ModelOption) => {
    const isSelected =
      currentSelection?.providerId === option.providerId &&
      currentSelection?.modelName === option.modelName &&
      currentSelection?.provider === option.providerKey;

    // Build description with recommendation badge
    const description = option.isRecommended ? "Recommended" : undefined;

    const rowIcon = getModelIcon(option.providerKey, option.modelName);
    const groupIcon = getModelIcon(option.providerKey);

    return (
      <div
        key={`${option.groupKey}-${option.modelName}`}
        ref={isSelected ? selectedItemRef : undefined}
      >
        <LineItemButton
          sizePreset="main-ui"
          variant="section"
          state={isSelected ? "selected" : "empty"}
          description={description}
          icon={rowIcon !== groupIcon ? rowIcon : undefined}
          onClick={() => applySelection(option)}
          rightChildren={
            isSelected ? (
              <SvgCheck className="h-4 w-4 stroke-action-selection-05 shrink-0" />
            ) : null
          }
          title={option.displayName}
        />
      </div>
    );
  };

  return (
    <Popover open={isOpen} onOpenChange={handlePopoverOpenChange}>
      <Popover.Trigger asChild>{children}</Popover.Trigger>
      <Popover.Content side="bottom" align="start" width="lg">
        <div className="px-3">
          <Section gap={2}>
            <div className="flex items-center justify-between py-3 gap-3 border-b border-border-01 px-1">
              <Text font="secondary-body" color="text-03">
                Recommended Models Only
              </Text>
              <Switch
                checked={showRecommendedOnly}
                onCheckedChange={handleRecommendedOnlyChange}
              />
            </div>

            <PopoverMenu scrollContainerRef={scrollContainerRef}>
              {groupedOptions.length === 0
                ? [
                    <div key="empty" className="py-3 px-2">
                      <Text font="secondary-body" color="text-03">
                        No models found
                      </Text>
                    </div>,
                  ]
                : [
                    <Accordion
                      key="accordion"
                      type="multiple"
                      value={expandedGroups}
                      onValueChange={handleAccordionChange}
                      className="w-full flex flex-col"
                    >
                      {groupedOptions.map((group) => {
                        const isExpanded = expandedGroups.includes(
                          group.groupKey
                        );
                        const ModelIcon = getModelIcon(group.providerKey);

                        return (
                          <AccordionItem
                            key={group.groupKey}
                            value={group.groupKey}
                            className="border-none pt-1"
                          >
                            <AccordionTrigger className="flex items-center rounded-08 hover:no-underline hover:bg-background-tint-02 group [&>svg]:hidden w-full py-1">
                              <div className="flex items-center gap-1 shrink-0">
                                <div className="flex items-center justify-center size-5 shrink-0">
                                  <ModelIcon size={16} />
                                </div>
                                <span className="px-0.5">
                                  <Text
                                    font="secondary-body"
                                    color="text-03"
                                    nowrap
                                  >
                                    {group.displayName}
                                  </Text>
                                </span>
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
          </Section>
        </div>
      </Popover.Content>
    </Popover>
  );
}
