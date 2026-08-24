"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import * as SliderPrimitive from "@radix-ui/react-slider";
import {
  Button,
  LineItemButton,
  Text,
  InputTypeIn,
  PopoverMenu,
  Tooltip,
} from "@opal/components";
import {
  SvgBarChart,
  SvgCheck,
  SvgChevronLeft,
  SvgChevronRight,
  SvgCode,
  SvgSliders,
  SvgThermometer,
} from "@opal/icons";
import { ContentAction, Section } from "@opal/layouts";
import { cn } from "@opal/utils";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import { Disabled, Hoverable, Interactive } from "@opal/core";
import {
  GLOBAL_DEFAULT_LLM_OPTION,
  LLMOption,
  ModelOptionProvider,
  buildLlmOptions,
  groupLlmOptions,
  llmOptionKey,
} from "@/lib/languageModels/options";
import { ReasoningEffortOverride } from "@/lib/languageModels/types";
import {
  ALL_REASONING_STOPS,
  PaneSlider,
  REASONING_STOP_LABELS,
  SettingRow,
  UNKNOWN_CONTEXT_TOOLTIP,
  UNSUPPORTED_SETTING_TOOLTIP,
  formatContextWindow,
  maxReasoningStop,
} from "@/sections/model-selector/setting-controls";
import { useCurrentAgentLLMProviders } from "@/lib/languageModels/hooks";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";

export interface TemperatureManager {
  temperature: number;
  updateTemperature: (value: number) => void;
  maxTemperature: number;
}

export interface ReasoningManager {
  reasoningEffort: ReasoningEffortOverride | null;
  updateReasoningEffort: (effort: ReasoningEffortOverride | null) => void;
}

/** Managers powering the per-model detail pane. A manager is absent when the
 * host offers no such control, or an admin withheld it; either way its row
 * does not render. Capability limits disable a row instead. */
export interface ModelDetailManagers {
  temperature?: TemperatureManager;
  reasoning?: ReasoningManager;
}

/**
 * Builds the detail-pane managers for a selector host. Each block is gated by
 * an admin setting: temperature on user.preferences.temperature_override_enabled
 * (a merge of the workspace setting and an unused per-user column), reasoning on
 * the workspace setting directly. The result is undefined when no block would
 * render, which also hides the drill-in affordance.
 */
export function useModelDetailManagers(
  temperatureManager?: TemperatureManager,
  reasoningManager?: ReasoningManager
): ModelDetailManagers | undefined {
  const { user } = useUser();
  const settings = useSettings();
  const temperatureOverrideEnabled =
    user?.preferences?.temperature_override_enabled;
  // Fail closed while the settings fetch is in flight: the placeholder says
  // enabled, which would flash the control into a workspace that withheld
  // it. Temperature fails closed here too, by way of an undefined user.
  const reasoningOverrideEnabled =
    !settings.isLoading && (settings.reasoning_override_enabled ?? true);
  return useMemo(() => {
    const temperature =
      temperatureManager && temperatureOverrideEnabled
        ? temperatureManager
        : undefined;
    const reasoning =
      reasoningManager && reasoningOverrideEnabled
        ? reasoningManager
        : undefined;
    return temperature || reasoning ? { temperature, reasoning } : undefined;
  }, [
    temperatureManager,
    reasoningManager,
    temperatureOverrideEnabled,
    reasoningOverrideEnabled,
  ]);
}

/** Highest stop this model supports, as a slider index. */
function maxSupportedReasoningStop(option: LLMOption): number {
  return maxReasoningStop(option.supportedReasoningEfforts);
}

/** Fixed-height scroll box: the popover clips overflow instead of scrolling. */
const DETAIL_PANE_HEIGHT_CLASS = "h-[352px]";

function EmptyIconSlot(props: IconProps) {
  return <div {...(props as any)} />;
}

function SelectedCheckIcon(props: IconProps) {
  return (
    <SvgCheck
      {...props}
      className={cn(props.className, "text-action-selection-05")}
    />
  );
}

/** Left icon slot for selectable rows: a blue check, or reserved space. */
function selectionIcon(selected: boolean): IconFunctionComponent {
  return selected ? SelectedCheckIcon : EmptyIconSlot;
}

interface ModelDetailPaneProps {
  option: LLMOption;
  managers: ModelDetailManagers;
  onBack: () => void;
}

function ModelDetailPane({ option, managers, onBack }: ModelDetailPaneProps) {
  // Backend pins temperature to 1 (or omits it) for reasoning models, so
  // the slider is locked at 1.
  const temperatureManager = managers.temperature;
  const reasoningManager = managers.reasoning;
  const temperatureEnabled = !option.supportsReasoning && !!temperatureManager;
  // A reasoning model with no supported levels takes no effort parameter at
  // all (e.g. o1-mini), so the row stays disabled.
  const maxSupportedStop = maxSupportedReasoningStop(option);
  const reasoningEnabled =
    option.supportsReasoning && !!reasoningManager && maxSupportedStop >= 0;

  // The slider spans all stops for uniform geometry and clamps input to the
  // max supported index. The lower bound keeps the disabled no-levels case on
  // a valid stop.
  const clampStop = (stop: number) =>
    Math.max(0, Math.min(stop, maxSupportedStop));

  const [localTemperature, setLocalTemperature] = useState(
    temperatureManager?.temperature ?? 0.5
  );
  // A stored level the model doesn't support (e.g. xhigh after switching
  // models) displays clamped to the highest supported stop.
  const storedStop = ALL_REASONING_STOPS.indexOf(
    reasoningManager?.reasoningEffort ?? "medium"
  );
  const [localEffortStop, setLocalEffortStop] = useState(
    clampStop(
      storedStop === -1 ? ALL_REASONING_STOPS.indexOf("medium") : storedStop
    )
  );

  const displayTemperature = temperatureEnabled ? localTemperature : 1;
  const effortLabel =
    REASONING_STOP_LABELS[ALL_REASONING_STOPS[localEffortStop] ?? "medium"];

  const maxTemperature = temperatureManager?.maxTemperature ?? 2;
  const temperatureFraction =
    maxTemperature > 0 ? displayTemperature / maxTemperature : 0;
  let temperatureAnchor = 1;
  if (temperatureFraction < 1 / 3) temperatureAnchor = 0;
  else if (temperatureFraction > 2 / 3) temperatureAnchor = 2;

  const contextLabel =
    option.maxInputTokens != null && option.maxInputTokens > 0
      ? formatContextWindow(option.maxInputTokens)
      : null;

  return (
    <div
      className={cn(
        DETAIL_PANE_HEIGHT_CLASS,
        "flex w-full flex-col gap-1 overflow-y-auto"
      )}
    >
      <div className="flex flex-row items-center gap-1 p-1">
        <Button
          icon={SvgChevronLeft}
          prominence="tertiary"
          size="sm"
          onClick={onBack}
        />
        <div className="flex min-w-0 flex-1 flex-row items-baseline justify-between gap-2">
          <Text font="main-ui-body" color="text-02" nowrap>
            {option.displayName}
          </Text>
          <div className="min-w-0 truncate">
            <Text font="secondary-body" color="text-02">
              {option.modelName}
            </Text>
          </div>
        </div>
      </div>

      <SettingRow
        icon={SvgCode}
        title="Context Window"
        value={contextLabel ?? "—"}
        valueTooltip={contextLabel ? undefined : UNKNOWN_CONTEXT_TOOLTIP}
        caption="Tokens limit for each session"
      />

      {/* A row is absent when an admin withheld the control, and greyed
          when the model cannot honour it. Greying the former would claim
          the model does not support a setting it does. */}
      {temperatureManager && (
        <SettingRow
          icon={SvgThermometer}
          title="Temperature"
          value={displayTemperature.toFixed(1)}
          caption="How predictable or creative the model should respond"
          disabled={!temperatureEnabled}
          disabledTooltip={UNSUPPORTED_SETTING_TOOLTIP}
        >
          <PaneSlider
            value={displayTemperature}
            min={0}
            max={maxTemperature}
            step={0.01}
            disabled={!temperatureEnabled}
            onValueChange={setLocalTemperature}
            onValueCommit={(value) =>
              temperatureManager?.updateTemperature(value)
            }
          />
          <div className="flex flex-row items-center justify-between">
            {["Deterministic", "Balanced", "Creative"].map((label, index) => (
              <Text
                key={label}
                font="figure-small-value"
                color={index === temperatureAnchor ? "text-04" : "text-02"}
              >
                {label}
              </Text>
            ))}
          </div>
        </SettingRow>
      )}

      {reasoningManager && (
        <SettingRow
          icon={SvgBarChart}
          title="Reasoning Level"
          value={effortLabel}
          caption="How much thinking the model should perform before answering"
          disabled={!reasoningEnabled}
          disabledTooltip={UNSUPPORTED_SETTING_TOOLTIP}
        >
          <PaneSlider
            value={localEffortStop}
            min={0}
            max={ALL_REASONING_STOPS.length - 1}
            step={1}
            disabled={!reasoningEnabled}
            onValueChange={(value) => setLocalEffortStop(clampStop(value))}
            onValueCommit={(value) => {
              const effort = ALL_REASONING_STOPS[clampStop(value)];
              if (effort) reasoningManager?.updateReasoningEffort(effort);
            }}
          />
          {/* Labels anchor at the slider's index/lastStop fractions so they
                line up with the stops. End labels align to the row edges to
                avoid overflow. */}
          <div className="relative h-4 w-full">
            {ALL_REASONING_STOPS.map((stop, index) => {
              const lastStop = ALL_REASONING_STOPS.length - 1;
              return (
                <div
                  key={stop}
                  className={cn(
                    "absolute top-0",
                    index === lastStop
                      ? "-translate-x-full"
                      : index > 0 && "-translate-x-1/2"
                  )}
                  style={{ left: `${(index / lastStop) * 100}%` }}
                >
                  <Disabled
                    disabled={reasoningEnabled && index > maxSupportedStop}
                    tooltip={UNSUPPORTED_SETTING_TOOLTIP}
                    tooltipSide="top"
                  >
                    <Text
                      font="figure-small-value"
                      color={
                        reasoningEnabled && index === localEffortStop
                          ? "text-04"
                          : "text-02"
                      }
                      nowrap
                    >
                      {REASONING_STOP_LABELS[stop]}
                    </Text>
                  </Disabled>
                </div>
              );
            })}
          </div>
        </SettingRow>
      )}
    </div>
  );
}

export interface ModelSelectorContentProps {
  currentModelName?: string;
  providerOptions?: ModelOptionProvider[];
  /**
   * Set by a host that fetches `providerOptions` itself, to report that the
   * fetch is still in flight. An empty list then reads as "not here yet"
   * instead of "no models".
   */
  isLoading?: boolean;
  includeHiddenModels?: boolean;
  requiresImageInput?: boolean;
  onSelect: (option: LLMOption) => void;
  isSelected: (option: LLMOption) => boolean;
  isDisabled?: (option: LLMOption) => boolean;
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
  /** When true, a "Global Default Model" entry is prepended to the list. */
  includeGlobalDefault?: boolean;
  /** When provided, model rows gain a drill-in settings pane. */
  modelDetail?: ModelDetailManagers;
}

export default function ModelSelectorContent({
  currentModelName,
  providerOptions,
  isLoading: isLoadingProp = false,
  includeHiddenModels = false,
  requiresImageInput,
  onSelect,
  isSelected,
  isDisabled,
  scrollContainerRef: externalScrollRef,
  includeGlobalDefault = false,
  modelDetail,
}: ModelSelectorContentProps) {
  const [detailOption, setDetailOption] = useState<LLMOption | null>(null);
  const {
    llmProviders: currentAgentProviderOptions,
    isLoading: currentAgentProvidersLoading,
    defaultText,
  } = useCurrentAgentLLMProviders();
  const llmProviders = providerOptions ?? currentAgentProviderOptions;
  const isLoading =
    isLoadingProp ||
    (providerOptions === undefined && currentAgentProvidersLoading);

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
    () => buildLlmOptions(llmProviders, currentModelName, includeHiddenModels),
    [llmProviders, currentModelName, includeHiddenModels]
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

    // Skip the model-id description when it would just repeat the display name.
    const description =
      option.modelName !== option.displayName ? option.modelName : undefined;

    return (
      <Disabled key={llmOptionKey(option)} disabled={disabled}>
        <Hoverable.Root group="model-row">
          <LineItemButton
            selectVariant="select-heavy"
            state={selected ? "selected" : "empty"}
            icon={selectionIcon(selected)}
            title={option.displayName}
            description={description}
            onClick={() => onSelect(option)}
            rightChildren={
              modelDetail ? (
                <Hoverable.Item group="model-row" variant="appear-on-hover">
                  <Button
                    icon={SvgSliders}
                    prominence="tertiary"
                    size="sm"
                    aria-label={`${option.displayName} settings`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setDetailOption(option);
                    }}
                  />
                </Hoverable.Item>
              ) : null
            }
            sizePreset="main-ui"
            rounding="sm"
          />
        </Hoverable.Root>
      </Disabled>
    );
  };

  if (detailOption && modelDetail) {
    return (
      <ModelDetailPane
        option={detailOption}
        managers={modelDetail}
        onBack={() => setDetailOption(null)}
      />
    );
  }

  return (
    <Section gap={2}>
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
                  icon={selectionIcon(isSelected(GLOBAL_DEFAULT_LLM_OPTION))}
                  title={GLOBAL_DEFAULT_LLM_OPTION.displayName}
                  description={globalDefaultDisplayName ?? undefined}
                  onClick={() => onSelect(GLOBAL_DEFAULT_LLM_OPTION)}
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
                    <Section key="single-provider" gap={1} alignItems="stretch">
                      {groupedOptions[0]!.options.map(renderModelItem)}
                    </Section>,
                  ]
                : groupedOptions.flatMap((group, groupIndex) => {
                    const open = isGroupOpen(group.key);
                    const collapsible = (
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
                              <div className="pl-2 pr-1 py-1 w-full rounded-08 bg-background-tint-01">
                                <ContentAction
                                  sizePreset="secondary"
                                  variant="body"
                                  color="muted"
                                  icon={group.Icon}
                                  title={group.displayName}
                                  padding={0}
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
                          <Section gap={1} alignItems="stretch">
                            {group.options.map(renderModelItem)}
                          </Section>
                        </CollapsibleContent>
                      </Collapsible>
                    );
                    // null children render as PopoverMenu divider lines.
                    return groupIndex > 0 ? [null, collapsible] : [collapsible];
                  })),
        ]}
      </PopoverMenu>
    </Section>
  );
}
