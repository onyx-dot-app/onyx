"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import {
  Button,
  LineItemButton,
  Text,
  InputTypeIn,
  PopoverMenu,
} from "@opal/components";
import { SvgCheck, SvgChevronRight } from "@opal/icons";
import { ContentAction, Section } from "@opal/layouts";
import { cn } from "@opal/utils";
import { Disabled, Interactive } from "@opal/core";
import {
  GLOBAL_DEFAULT_LLM_OPTION,
  LLMOption,
  buildLlmOptions,
  groupLlmOptions,
} from "@/lib/languageModels/options";
import { useCurrentAgentLLMProviders } from "@/lib/languageModels/hooks";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";

export interface ModelSelectorContentProps {
  currentModelName?: string;
  requiresImageInput?: boolean;
  onSelect: (option: LLMOption) => void;
  isSelected: (option: LLMOption) => boolean;
  isDisabled?: (option: LLMOption) => boolean;
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
  /** When true, a "Global Default Model" entry is prepended to the list. */
  includeGlobalDefault?: boolean;
  footer?: React.ReactNode;
}

export default function ModelSelectorContent({
  currentModelName,
  requiresImageInput,
  onSelect,
  isSelected,
  isDisabled,
  scrollContainerRef: externalScrollRef,
  includeGlobalDefault = false,
  footer,
}: ModelSelectorContentProps) {
  const { llmProviders, isLoading, defaultText } =
    useCurrentAgentLLMProviders();

  const globalDefaultDisplayName = useMemo(() => {
    if (!defaultText || !llmProviders) return null;
    const provider = llmProviders.find((p) => p.id === defaultText.provider_id);
    const mc = provider?.model_configurations.find(
      (m) => m.name === defaultText.model_name
    );
    return mc?.effectiveDisplayName ?? null;
  }, [defaultText, llmProviders]);
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
      <Disabled
        key={`${option.provider}:${option.modelName}`}
        disabled={disabled}
      >
        <LineItemButton
          selectVariant="select-heavy"
          state={selected ? "selected" : "empty"}
          icon={(props) => <div {...(props as any)} />}
          title={option.displayName}
          description={description}
          onClick={() => onSelect(option)}
          rightChildren={
            selected ? (
              <div className="flex h-5 items-center">
                <SvgCheck className="text-action-link-05" size={16} />
              </div>
            ) : null
          }
          sizePreset="main-ui"
          rounding="sm"
        />
      </Disabled>
    );
  };

  return (
    <Section gap={0.5}>
      <InputTypeIn
        searchIcon
        variant="internal"
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        placeholder="Search models..."
      />

      <PopoverMenu scrollContainerRef={scrollContainerRef}>
        {[
          ...(includeGlobalDefault && !isLoading
            ? [
                <LineItemButton
                  key="global-default"
                  selectVariant="select-heavy"
                  state={
                    isSelected(GLOBAL_DEFAULT_LLM_OPTION) ? "selected" : "empty"
                  }
                  icon={(props) => <div {...(props as any)} />}
                  title={GLOBAL_DEFAULT_LLM_OPTION.displayName}
                  description={globalDefaultDisplayName ?? undefined}
                  onClick={() => onSelect(GLOBAL_DEFAULT_LLM_OPTION)}
                  rightChildren={
                    isSelected(GLOBAL_DEFAULT_LLM_OPTION) ? (
                      <div className="flex h-5 items-center">
                        <SvgCheck className="text-action-link-05" size={16} />
                      </div>
                    ) : null
                  }
                  sizePreset="main-ui"
                  rounding="sm"
                />,
              ]
            : []),
          null,
          ...(isLoading
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
                    <Section
                      key="single-provider"
                      gap={0.25}
                      alignItems="stretch"
                    >
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
                        className="flex flex-col gap-1"
                      >
                        <CollapsibleTrigger asChild>
                          <Interactive.Stateless prominence="tertiary">
                            <Interactive.Container
                              size="fit"
                              rounding="sm"
                              width="full"
                            >
                              <div className="pl-2 pr-1 py-1 w-full">
                                <ContentAction
                                  sizePreset="secondary"
                                  variant="body"
                                  color="muted"
                                  icon={group.Icon}
                                  title={group.displayName}
                                  padding="fit"
                                  rightChildren={
                                    <Section>
                                      <Button
                                        icon={(props) => (
                                          <SvgChevronRight
                                            {...props}
                                            className={cn(
                                              "transition-all",
                                              open && "rotate-90",
                                              props.className
                                            )}
                                          />
                                        )}
                                        prominence="tertiary"
                                        size="sm"
                                      />
                                    </Section>
                                  }
                                  center
                                />
                              </div>
                            </Interactive.Container>
                          </Interactive.Stateless>
                        </CollapsibleTrigger>

                        <CollapsibleContent>
                          <Section gap={0.25} alignItems="stretch">
                            {group.options.map(renderModelItem)}
                          </Section>
                        </CollapsibleContent>
                      </Collapsible>
                    );
                  })),
        ]}
      </PopoverMenu>

      {footer}
    </Section>
  );
}
