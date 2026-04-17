"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import { PopoverMenu } from "@/refresh-components/Popover";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { Text } from "@opal/components";
import { SvgCheck, SvgChevronDown, SvgChevronRight } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { LLMOption } from "./interfaces";
import { buildLlmOptions, groupLlmOptions } from "./LLMPopover";
import LineItem from "@/refresh-components/buttons/LineItem";
import { LLMProviderDescriptor } from "@/interfaces/llm";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";

export interface ModelListContentProps {
  llmProviders: LLMProviderDescriptor[] | undefined;
  currentModelName?: string;
  requiresImageInput?: boolean;
  onSelect: (option: LLMOption) => void;
  isSelected: (option: LLMOption) => boolean;
  isDisabled?: (option: LLMOption) => boolean;
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
  isLoading?: boolean;
  footer?: React.ReactNode;
}

export default function ModelListContent({
  llmProviders,
  currentModelName,
  requiresImageInput,
  onSelect,
  isSelected,
  isDisabled,
  scrollContainerRef: externalScrollRef,
  isLoading,
  footer,
}: ModelListContentProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const internalScrollRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = externalScrollRef ?? internalScrollRef;

  const llmOptions = useMemo(
    () => buildLlmOptions(llmProviders, currentModelName),
    [llmProviders, currentModelName]
  );

  const filteredOptions = useMemo(() => {
    let result = llmOptions;
    if (requiresImageInput) {
      result = result.filter((opt) => opt.supportsImageInput);
    }
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (opt) =>
          opt.displayName.toLowerCase().includes(query) ||
          opt.modelName.toLowerCase().includes(query) ||
          (opt.vendor && opt.vendor.toLowerCase().includes(query))
      );
    }
    return result;
  }, [llmOptions, searchQuery, requiresImageInput]);

  const groupedOptions = useMemo(
    () => groupLlmOptions(filteredOptions),
    [filteredOptions]
  );

  // Find which group contains a currently-selected model (for auto-expand)
  const defaultGroupKey = useMemo(() => {
    for (const group of groupedOptions) {
      if (group.options.some((opt) => isSelected(opt))) {
        return group.key;
      }
    }
    return groupedOptions[0]?.key ?? "";
  }, [groupedOptions, isSelected]);

  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    new Set([defaultGroupKey])
  );

  // Reset expanded groups when default changes (e.g. popover re-opens)
  useEffect(() => {
    setExpandedGroups(new Set([defaultGroupKey]));
  }, [defaultGroupKey]);

  const isSearching = searchQuery.trim().length > 0;

  const toggleGroup = (key: string) => {
    if (isSearching) return;
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const isGroupOpen = (key: string) => isSearching || expandedGroups.has(key);

  const renderModelItem = (option: LLMOption) => {
    const selected = isSelected(option);
    const disabled = isDisabled?.(option) ?? false;

    const capabilities: string[] = [];
    if (option.supportsReasoning) capabilities.push("Reasoning");
    if (option.supportsImageInput) capabilities.push("Vision");
    const description =
      capabilities.length > 0 ? capabilities.join(", ") : undefined;

    return (
      <LineItem
        key={`${option.provider}:${option.modelName}`}
        selected={selected}
        disabled={disabled}
        description={description}
        onClick={() => onSelect(option)}
        rightChildren={
          selected ? (
            <SvgCheck className="h-4 w-4 stroke-action-link-05 shrink-0" />
          ) : null
        }
      >
        {option.displayName}
      </LineItem>
    );
  };

  return (
    <Section gap={0.5}>
      <InputTypeIn
        leftSearchIcon
        variant="internal"
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        placeholder="Search models..."
      />

      <PopoverMenu scrollContainerRef={scrollContainerRef}>
        {isLoading
          ? [
              <Text key="loading" font="secondary-body" color="text-03">
                Loading models...
              </Text>,
            ]
          : groupedOptions.length === 0
            ? [
                <Text key="empty" font="secondary-body" color="text-03">
                  No models found
                </Text>,
              ]
            : groupedOptions.length === 1
              ? [
                  <Section key="single-provider" gap={0.25}>
                    {groupedOptions[0]!.options.map(renderModelItem)}
                  </Section>,
                ]
              : groupedOptions.map((group) => {
                  const open = isGroupOpen(group.key);
                  return (
                    <Collapsible
                      key={group.key}
                      open={open}
                      onOpenChange={() => toggleGroup(group.key)}
                    >
                      <CollapsibleTrigger asChild>
                        <LineItem
                          muted
                          icon={group.Icon}
                          strokeIcon={false}
                          rightChildren={
                            open ? (
                              <SvgChevronDown className="h-4 w-4 stroke-text-04 shrink-0" />
                            ) : (
                              <SvgChevronRight className="h-4 w-4 stroke-text-04 shrink-0" />
                            )
                          }
                        >
                          {group.displayName}
                        </LineItem>
                      </CollapsibleTrigger>

                      <CollapsibleContent>
                        <Section gap={0.25}>
                          {group.options.map(renderModelItem)}
                        </Section>
                      </CollapsibleContent>
                    </Collapsible>
                  );
                })}
      </PopoverMenu>

      {footer}
    </Section>
  );
}
