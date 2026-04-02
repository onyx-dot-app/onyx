"use client";

import { useState, useMemo, useRef } from "react";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import { LlmManager } from "@/lib/hooks";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { Text } from "@opal/components";
import { Button } from "@opal/components";
import {
  SvgCheck,
  SvgChevronDown,
  SvgChevronRight,
  SvgPlusCircle,
  SvgX,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import {
  LLMOption,
  LLMOptionGroup,
} from "@/refresh-components/popovers/interfaces";
import {
  buildLlmOptions,
  groupLlmOptions,
} from "@/refresh-components/popovers/LLMPopover";
import * as AccordionPrimitive from "@radix-ui/react-accordion";
import { cn } from "@/lib/utils";

export const MAX_MODELS = 3;

export interface SelectedModel {
  name: string;
  provider: string;
  modelName: string;
  displayName: string;
}

export interface ModelSelectorProps {
  llmManager: LlmManager;
  selectedModels: SelectedModel[];
  onAdd: (model: SelectedModel) => void;
  onRemove: (index: number) => void;
  onReplace: (index: number, model: SelectedModel) => void;
}

/** Vertical 1px divider between model bar elements */
function BarDivider() {
  return <div className="h-9 w-px bg-border-01 shrink-0" />;
}

/** Individual model pill in the model bar */
function ModelPill({
  model,
  isMultiModel,
  onRemove,
  onClick,
}: {
  model: SelectedModel;
  isMultiModel: boolean;
  onRemove?: () => void;
  onClick?: () => void;
}) {
  const ProviderIcon = getProviderIcon(model.provider, model.modelName);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick?.();
        }
      }}
      className={cn(
        "flex items-center gap-0.5 rounded-12 p-2 shrink-0 cursor-pointer",
        "hover:bg-background-tint-02 transition-colors",
        isMultiModel && "bg-background-tint-02"
      )}
    >
      <div className="flex items-center justify-center size-5 shrink-0 p-0.5">
        <ProviderIcon size={16} />
      </div>
      <span className="px-1">
        <Text font="main-ui-action" color="text-04" nowrap>
          {model.displayName}
        </Text>
      </span>
      {isMultiModel ? (
        <Button
          prominence="tertiary"
          icon={SvgX}
          size="2xs"
          onClick={(e) => {
            e.stopPropagation();
            onRemove?.();
          }}
          tooltip="Remove model"
        />
      ) : (
        <SvgChevronDown className="size-4 stroke-text-03 shrink-0" />
      )}
    </div>
  );
}

/** Model item row inside the add-model popover */
function ModelItem({
  option,
  isSelected,
  isDisabled,
  onToggle,
}: {
  option: LLMOption;
  isSelected: boolean;
  isDisabled: boolean;
  onToggle: () => void;
}) {
  const ProviderIcon = getProviderIcon(option.provider, option.modelName);

  // Build subtitle from model capabilities
  const subtitle = useMemo(() => {
    const parts: string[] = [];
    if (option.supportsReasoning) parts.push("reasoning");
    if (option.supportsImageInput) parts.push("multi-modal");
    if (parts.length === 0 && option.modelName) return option.modelName;
    return parts.join(", ");
  }, [option]);

  return (
    <button
      type="button"
      disabled={isDisabled}
      onClick={onToggle}
      className={cn(
        "flex items-center gap-1.5 w-full rounded-08 p-1.5 text-left transition-colors",
        isSelected ? "bg-action-link-01" : "hover:bg-background-tint-02",
        isDisabled && !isSelected && "opacity-50 cursor-not-allowed"
      )}
    >
      <div className="flex items-center justify-center size-5 shrink-0 p-0.5">
        <ProviderIcon size={16} />
      </div>
      <div className="flex flex-col flex-1 min-w-0">
        <span
          className={cn(isSelected ? "text-action-link-03" : "text-text-04")}
        >
          <Text font="main-ui-action" color="inherit" nowrap>
            {option.displayName}
          </Text>
        </span>
        {subtitle && (
          <Text font="secondary-body" color="text-03" nowrap>
            {subtitle}
          </Text>
        )}
      </div>
      {isSelected && (
        <span className="text-action-link-05 shrink-0">
          <Text font="secondary-body" color="inherit" nowrap>
            Added
          </Text>
        </span>
      )}
    </button>
  );
}

export default function ModelSelector({
  llmManager,
  selectedModels,
  onAdd,
  onRemove,
  onReplace,
}: ModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  // null = add mode (via + button), number = replace mode (via pill click)
  const [replacingIndex, setReplacingIndex] = useState<number | null>(null);

  const isMultiModel = selectedModels.length > 1;
  const atMax = selectedModels.length >= MAX_MODELS;

  const llmOptions = useMemo(
    () => buildLlmOptions(llmManager.llmProviders),
    [llmManager.llmProviders]
  );

  const selectedKeys = useMemo(
    () => new Set(selectedModels.map((m) => `${m.provider}:${m.modelName}`)),
    [selectedModels]
  );

  const filteredOptions = useMemo(() => {
    if (!searchQuery.trim()) return llmOptions;
    const query = searchQuery.toLowerCase();
    return llmOptions.filter(
      (opt) =>
        opt.displayName.toLowerCase().includes(query) ||
        opt.modelName.toLowerCase().includes(query) ||
        (opt.vendor && opt.vendor.toLowerCase().includes(query))
    );
  }, [llmOptions, searchQuery]);

  const groupedOptions = useMemo(
    () => groupLlmOptions(filteredOptions),
    [filteredOptions]
  );

  const isSearching = searchQuery.trim().length > 0;

  // In replace mode, other selected models (not the one being replaced) are disabled
  const otherSelectedKeys = useMemo(() => {
    if (replacingIndex === null) return new Set<string>();
    return new Set(
      selectedModels
        .filter((_, i) => i !== replacingIndex)
        .map((m) => `${m.provider}:${m.modelName}`)
    );
  }, [selectedModels, replacingIndex]);

  // Current model at the replacing index (shows as "selected" in replace mode)
  const replacingKey = useMemo(() => {
    if (replacingIndex === null) return null;
    const m = selectedModels[replacingIndex];
    return m ? `${m.provider}:${m.modelName}` : null;
  }, [selectedModels, replacingIndex]);

  const getItemState = (optKey: string) => {
    if (replacingIndex !== null) {
      // Replace mode
      return {
        isSelected: optKey === replacingKey,
        isDisabled: otherSelectedKeys.has(optKey),
      };
    }
    // Add mode
    return {
      isSelected: selectedKeys.has(optKey),
      isDisabled: !selectedKeys.has(optKey) && atMax,
    };
  };

  const handleSelectModel = (option: LLMOption) => {
    const model: SelectedModel = {
      name: option.name,
      provider: option.provider,
      modelName: option.modelName,
      displayName: option.displayName,
    };

    if (replacingIndex !== null) {
      // Replace mode: swap the model at the clicked pill's index
      onReplace(replacingIndex, model);
      setOpen(false);
      setReplacingIndex(null);
      setSearchQuery("");
      return;
    }

    // Add mode: toggle (add/remove)
    const key = `${option.provider}:${option.modelName}`;
    const existingIndex = selectedModels.findIndex(
      (m) => `${m.provider}:${m.modelName}` === key
    );
    if (existingIndex >= 0) {
      onRemove(existingIndex);
    } else if (!atMax) {
      onAdd(model);
    }
  };

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setReplacingIndex(null);
      setSearchQuery("");
    }
  };

  const handlePillClick = (index: number) => {
    setReplacingIndex(index);
    setOpen(true);
  };

  return (
    <div className="flex items-center justify-end gap-1 p-1">
      {/* (+) Add model button — hidden at max models */}
      {!atMax && (
        <Popover open={open} onOpenChange={handleOpenChange}>
          <Popover.Trigger asChild>
            <Button
              prominence="tertiary"
              icon={SvgPlusCircle}
              size="sm"
              tooltip="Add Model"
            />
          </Popover.Trigger>

          <Popover.Content side="top" align="start" width="lg">
            <Section gap={0.25}>
              <InputTypeIn
                leftSearchIcon
                variant="internal"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search models..."
              />

              <PopoverMenu scrollContainerRef={scrollContainerRef}>
                {groupedOptions.length === 0
                  ? [
                      <div key="empty" className="py-3 px-2">
                        <Text font="secondary-body" color="text-03">
                          No models found
                        </Text>
                      </div>,
                    ]
                  : groupedOptions.length === 1
                    ? [
                        <div key="single" className="flex flex-col gap-0.5">
                          {groupedOptions[0]!.options.map((opt) => {
                            const key = `${opt.provider}:${opt.modelName}`;
                            const state = getItemState(key);
                            return (
                              <ModelItem
                                key={opt.modelName}
                                option={opt}
                                isSelected={state.isSelected}
                                isDisabled={state.isDisabled}
                                onToggle={() => handleSelectModel(opt)}
                              />
                            );
                          })}
                        </div>,
                      ]
                    : [
                        <ModelGroupAccordion
                          key="accordion"
                          groups={groupedOptions}
                          isSearching={isSearching}
                          getItemState={getItemState}
                          onToggle={handleSelectModel}
                        />,
                      ]}
              </PopoverMenu>
            </Section>
          </Popover.Content>
        </Popover>
      )}

      {/* Divider + model pills */}
      {selectedModels.length > 0 && (
        <>
          <BarDivider />
          {selectedModels.map((model, index) => (
            <div
              key={`${model.provider}:${model.modelName}`}
              className="flex items-center gap-1"
            >
              {index > 0 && <BarDivider />}
              <ModelPill
                model={model}
                isMultiModel={isMultiModel}
                onRemove={() => onRemove(index)}
                onClick={() => handlePillClick(index)}
              />
            </div>
          ))}
        </>
      )}
    </div>
  );
}

interface ModelGroupAccordionProps {
  groups: LLMOptionGroup[];
  isSearching: boolean;
  getItemState: (key: string) => { isSelected: boolean; isDisabled: boolean };
  onToggle: (option: LLMOption) => void;
}

function ModelGroupAccordion({
  groups,
  isSearching,
  getItemState,
  onToggle,
}: ModelGroupAccordionProps) {
  const allKeys = groups.map((g) => g.key);
  const [expandedGroups, setExpandedGroups] = useState<string[]>([
    allKeys[0] ?? "",
  ]);

  const effectiveExpanded = isSearching ? allKeys : expandedGroups;

  return (
    <AccordionPrimitive.Root
      type="multiple"
      value={effectiveExpanded}
      onValueChange={(value) => {
        if (!isSearching) setExpandedGroups(value);
      }}
      className="w-full flex flex-col"
    >
      {groups.map((group) => {
        const isExpanded = effectiveExpanded.includes(group.key);
        return (
          <AccordionPrimitive.Item
            key={group.key}
            value={group.key}
            className="pt-1"
          >
            <AccordionPrimitive.Header className="flex">
              <AccordionPrimitive.Trigger className="flex items-center rounded-08 hover:bg-background-tint-02 w-full py-1">
                <div className="flex items-center gap-1 shrink-0">
                  <div className="flex items-center justify-center size-5 shrink-0">
                    <group.Icon size={16} />
                  </div>
                  <span className="px-0.5">
                    <Text font="secondary-body" color="text-03" nowrap>
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
              </AccordionPrimitive.Trigger>
            </AccordionPrimitive.Header>
            <AccordionPrimitive.Content className="overflow-hidden data-[state=closed]:animate-accordion-up data-[state=open]:animate-accordion-down">
              <div className="flex flex-col gap-0.5 pt-0 pb-0">
                {group.options.map((opt) => {
                  const key = `${opt.provider}:${opt.modelName}`;
                  const state = getItemState(key);
                  return (
                    <ModelItem
                      key={key}
                      option={opt}
                      isSelected={state.isSelected}
                      isDisabled={state.isDisabled}
                      onToggle={() => onToggle(opt)}
                    />
                  );
                })}
              </div>
            </AccordionPrimitive.Content>
          </AccordionPrimitive.Item>
        );
      })}
    </AccordionPrimitive.Root>
  );
}
