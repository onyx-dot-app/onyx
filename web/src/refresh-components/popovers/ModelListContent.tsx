"use client";

import { useState, useMemo, useRef } from "react";
import { PopoverMenu } from "@/refresh-components/Popover";
import Separator from "@/refresh-components/Separator";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { Text } from "@opal/components";
import { SvgCheck } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { LLMOption } from "./interfaces";
import { buildLlmOptions, groupLlmOptions } from "./LLMPopover";
import LineItem from "@/refresh-components/buttons/LineItem";
import { LLMProviderDescriptor } from "@/interfaces/llm";

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
              <div key="loading" className="py-3 px-2">
                <Text font="secondary-body" color="text-03">
                  Loading models...
                </Text>
              </div>,
            ]
          : groupedOptions.length === 0
            ? [
                <div key="empty" className="py-3 px-2">
                  <Text font="secondary-body" color="text-03">
                    No models found
                  </Text>
                </div>,
              ]
            : groupedOptions.map((group) => (
                <div key={group.key}>
                  {groupedOptions.length > 1 && (
                    <Section
                      flexDirection="row"
                      gap={0.25}
                      padding={0}
                      height="auto"
                      alignItems="center"
                      justifyContent="start"
                      className="px-2 pt-2 pb-1"
                    >
                      <div className="flex items-center gap-1 shrink-0">
                        <group.Icon size={16} />
                        <Text font="secondary-body" color="text-03" nowrap>
                          {group.displayName}
                        </Text>
                      </div>
                      <Separator noPadding className="flex-1" />
                    </Section>
                  )}
                  <Section
                    gap={0.25}
                    alignItems="stretch"
                    justifyContent="start"
                  >
                    {group.options.map(renderModelItem)}
                  </Section>
                </div>
              ))}
      </PopoverMenu>

      {footer}
    </Section>
  );
}
