"use client";

import { useState, useMemo, useRef } from "react";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import { LlmManager } from "@/lib/hooks";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { Text, Button, SelectButton, OpenButton } from "@opal/components";
import {
  SvgCheck,
  SvgChevronDown,
  SvgChevronRight,
  SvgPlusCircle,
  SvgX,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { LLMOption } from "@/refresh-components/popovers/interfaces";
import {
  buildLlmOptions,
  groupLlmOptions,
} from "@/refresh-components/popovers/LLMPopover";
import LineItem from "@/refresh-components/buttons/LineItem";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

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

function modelKey(provider: string, modelName: string): string {
  return `${provider}:${modelName}`;
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
    () => new Set(selectedModels.map((m) => modelKey(m.provider, m.modelName))),
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

  const otherSelectedKeys = useMemo(() => {
    if (replacingIndex === null) return new Set<string>();
    return new Set(
      selectedModels
        .filter((_, i) => i !== replacingIndex)
        .map((m) => modelKey(m.provider, m.modelName))
    );
  }, [selectedModels, replacingIndex]);

  const replacingKey =
    replacingIndex !== null
      ? (() => {
          const m = selectedModels[replacingIndex];
          return m ? modelKey(m.provider, m.modelName) : null;
        })()
      : null;

  // Accordion: expand first group on open, force-expand all during search
  const [expandedGroups, setExpandedGroups] = useState<string[]>([]);

  const effectiveExpandedGroups = useMemo(() => {
    if (isSearching) return groupedOptions.map((g) => g.key);
    return expandedGroups;
  }, [isSearching, groupedOptions, expandedGroups]);

  const getItemState = (optKey: string) => {
    if (replacingIndex !== null) {
      return {
        isSelected: optKey === replacingKey,
        isDisabled: otherSelectedKeys.has(optKey),
      };
    }
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
      onReplace(replacingIndex, model);
      setOpen(false);
      setReplacingIndex(null);
      setSearchQuery("");
      return;
    }

    const key = modelKey(option.provider, option.modelName);
    const existingIndex = selectedModels.findIndex(
      (m) => modelKey(m.provider, m.modelName) === key
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
    } else {
      // Initialize accordion expansion on open
      const allKeys = groupedOptions.map((g) => g.key);
      setExpandedGroups(allKeys.length > 0 ? [allKeys[0]!] : []);
    }
  };

  const handlePillClick = (index: number) => {
    setReplacingIndex(index);
    // Initialize accordion + open popover in one handler (no effect needed)
    const allKeys = groupedOptions.map((g) => g.key);
    setExpandedGroups(allKeys.length > 0 ? [allKeys[0]!] : []);
    setOpen(true);
  };

  const renderModelItem = (option: LLMOption) => {
    const key = modelKey(option.provider, option.modelName);
    const { isSelected, isDisabled } = getItemState(key);

    const capabilities: string[] = [];
    if (option.supportsReasoning) capabilities.push("Reasoning");
    if (option.supportsImageInput) capabilities.push("Vision");
    const description =
      capabilities.length > 0 ? capabilities.join(", ") : undefined;

    return (
      <LineItem
        key={key}
        selected={isSelected}
        disabled={isDisabled}
        description={description}
        onClick={() => handleSelectModel(option)}
        rightChildren={
          isSelected ? (
            <SvgCheck className="h-4 w-4 stroke-action-link-05 shrink-0" />
          ) : null
        }
      >
        {option.displayName}
      </LineItem>
    );
  };

  const popoverContent = (
    <Section gap={0.5}>
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
                <div key="single-provider" className="flex flex-col gap-1">
                  {groupedOptions[0]!.options.map(renderModelItem)}
                </div>,
              ]
            : [
                <Accordion
                  key="accordion"
                  type="multiple"
                  value={effectiveExpandedGroups}
                  onValueChange={(value) => {
                    if (!isSearching) setExpandedGroups(value);
                  }}
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
                        <AccordionTrigger className="flex items-center rounded-08 hover:no-underline hover:bg-background-tint-02 group [&>svg]:hidden w-full py-1">
                          <div className="flex items-center gap-1 shrink-0">
                            <div className="flex items-center justify-center size-5 shrink-0">
                              <group.Icon size={16} />
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
  );

  return (
    <div className="flex items-center justify-end gap-1 p-1">
      <Popover open={open} onOpenChange={handleOpenChange}>
        {!atMax && (
          <Popover.Trigger asChild>
            <Button
              prominence="tertiary"
              icon={SvgPlusCircle}
              size="sm"
              tooltip="Add Model"
            />
          </Popover.Trigger>
        )}

        <Popover.Content side="top" align="start" width="lg">
          {popoverContent}
        </Popover.Content>
      </Popover>

      {selectedModels.length > 0 && isMultiModel && (
        <div className="h-9 w-px bg-border-01 shrink-0" />
      )}

      {selectedModels.map((model, index) => {
        const ProviderIcon = getProviderIcon(model.provider, model.modelName);

        if (!isMultiModel) {
          return (
            <OpenButton
              key={modelKey(model.provider, model.modelName)}
              icon={ProviderIcon}
              onClick={() => handlePillClick(index)}
            >
              {model.displayName}
            </OpenButton>
          );
        }

        return (
          <div
            key={modelKey(model.provider, model.modelName)}
            className="flex items-center gap-1"
          >
            {index > 0 && <div className="h-9 w-px bg-border-01 shrink-0" />}
            <SelectButton
              icon={ProviderIcon}
              state="empty"
              variant="select-tinted"
              interaction="hover"
              onClick={() => handlePillClick(index)}
            >
              {model.displayName}
            </SelectButton>
            <Button
              prominence="tertiary"
              icon={SvgX}
              size="2xs"
              onClick={() => onRemove(index)}
              tooltip="Remove model"
            />
          </div>
        );
      })}
    </div>
  );
}
