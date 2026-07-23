"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import * as SliderPrimitive from "@radix-ui/react-slider";
import {
  Button,
  LineItemButton,
  Text,
  InputTypeIn,
  PopoverMenu,
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
import type { IconFunctionComponent } from "@opal/types";
import { Disabled, Hoverable, Interactive } from "@opal/core";
import {
  GLOBAL_DEFAULT_LLM_OPTION,
  LLMOption,
  buildLlmOptions,
  groupLlmOptions,
  llmOptionKey,
} from "@/lib/languageModels/options";
import { ReasoningEffortOverride } from "@/lib/languageModels/types";
import { useCurrentAgentLLMProviders } from "@/lib/languageModels/hooks";
import { useUser } from "@/providers/UserProvider";
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

/** Managers powering the per-model detail pane. Rows always render, and an absent manager leaves its row disabled. */
export interface ModelDetailManagers {
  temperature?: TemperatureManager;
  reasoning?: ReasoningManager;
}

/**
 * Builds the detail-pane managers for a selector host. Temperature is gated
 * on user.preferences.temperature_override_enabled. The result is undefined
 * when no block would render.
 */
export function useModelDetailManagers(
  temperatureManager?: TemperatureManager,
  reasoningManager?: ReasoningManager
): ModelDetailManagers | undefined {
  const { user } = useUser();
  const temperatureOverrideEnabled =
    user?.preferences?.temperature_override_enabled;
  return useMemo(() => {
    const temperature =
      temperatureManager && temperatureOverrideEnabled
        ? temperatureManager
        : undefined;
    return temperature || reasoningManager
      ? { temperature, reasoning: reasoningManager }
      : undefined;
  }, [temperatureManager, reasoningManager, temperatureOverrideEnabled]);
}

const BASE_REASONING_STOPS: ReasoningEffortOverride[] = [
  "off",
  "low",
  "medium",
  "high",
];

/** Every stop the slider renders. Unsupported stops are greyed, never hidden. */
const ALL_REASONING_STOPS: ReasoningEffortOverride[] = [
  ...BASE_REASONING_STOPS,
  "xhigh",
];

const REASONING_STOP_LABELS: Record<ReasoningEffortOverride, string> = {
  off: "Off",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "XHigh",
};

/** Providers whose models can be true OpenAI models (responses API). */
const TRUE_OPENAI_PROVIDERS = new Set(["openai", "azure", "litellm_proxy"]);

/**
 * Approximates the backend's _parse_anthropic_model_version. Segments longer
 * than two digits are date snapshots, not minor versions, and parse as 0.
 */
function anthropicModelVersion(modelName: string): [number, number] | null {
  const name = modelName.toLowerCase();
  const claudeIndex = name.indexOf("claude");
  if (claudeIndex === -1) return null;
  const match = name.slice(claudeIndex).match(/\d+(?:[.-]\d+)?/);
  if (!match) return null;
  const parts = match[0].split(/[.-]/);
  if (!parts[0]) return null;
  const minor = parts[1] && parts[1].length <= 2 ? parseInt(parts[1], 10) : 0;
  return [parseInt(parts[0], 10), minor];
}

/**
 * Display-side mirror of the backend capability checks: xhigh is supported by
 * true OpenAI models and by Anthropic adaptive-thinking models (Claude >= 4.7,
 * matching _anthropic_uses_adaptive_thinking). The backend clamps unsupported
 * levels or strips rejected reasoning params and retries, so an imperfect
 * match here degrades gracefully.
 */
function modelSupportsXhigh(option: LLMOption): boolean {
  const openAiXhigh =
    TRUE_OPENAI_PROVIDERS.has(option.provider) &&
    /^(gpt-|o\d)/i.test(option.modelName);
  const claudeVersion = anthropicModelVersion(option.modelName);
  const anthropicXhigh =
    claudeVersion !== null &&
    (claudeVersion[0] > 4 || (claudeVersion[0] === 4 && claudeVersion[1] >= 7));
  return openAiXhigh || anthropicXhigh;
}

function formatContextWindow(tokens: number): string {
  if (tokens >= 1_000_000)
    return `${(tokens / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  return tokens >= 1000 ? `${Math.round(tokens / 1000)}K` : `${tokens}`;
}

const CONTEXT_AXIS_STOPS = [
  200_000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000,
];

function contextAxisMax(tokens: number): number {
  return CONTEXT_AXIS_STOPS.find((stop) => stop >= tokens) ?? tokens;
}

/** Both views render at this height so the popover never resizes. */
const PANE_HEIGHT_CLASS = "h-[352px]";

const SLIDER_THUMB_CLASS =
  "block size-3 rounded-full bg-background-neutral-00 shadow-[0_0_2px_1px_rgba(0,0,0,0.15)] focus:outline-none";
const SLIDER_TRACK_CLASS =
  "h-1.5 w-full overflow-hidden rounded bg-background-tint-02";
const SLIDER_FILL_CLASS = "h-full bg-theme-primary-05";

/** Left icon slot for selectable rows: a blue check, or reserved space. */
function selectionIcon(selected: boolean): IconFunctionComponent {
  if (!selected) return (props) => <div {...(props as any)} />;
  return (props) => (
    <SvgCheck
      {...(props as any)}
      className={cn((props as any).className, "text-action-link-05")}
    />
  );
}

interface PaneSliderProps {
  value: number;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  onValueChange: (value: number) => void;
  onValueCommit: (value: number) => void;
}

function PaneSlider({
  value,
  min,
  max,
  step,
  disabled,
  onValueChange,
  onValueCommit,
}: PaneSliderProps) {
  return (
    <SliderPrimitive.Root
      className="relative flex h-7 w-full touch-none select-none items-center"
      value={[value]}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      onValueChange={(vals) => vals[0] !== undefined && onValueChange(vals[0])}
      onValueCommit={(vals) => vals[0] !== undefined && onValueCommit(vals[0])}
    >
      <SliderPrimitive.Track
        className={cn(SLIDER_TRACK_CLASS, "relative grow")}
      >
        <SliderPrimitive.Range className={cn(SLIDER_FILL_CLASS, "absolute")} />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb className={SLIDER_THUMB_CLASS} />
    </SliderPrimitive.Root>
  );
}

/** Read-only gauge matching the PaneSlider look, for informational rows. */
function ContextGauge({ fraction }: { fraction: number }) {
  const pct = Math.min(100, Math.max(0, fraction * 100));
  return (
    <div className="relative flex h-7 w-full items-center">
      <div className={SLIDER_TRACK_CLASS}>
        <div className={SLIDER_FILL_CLASS} style={{ width: `${pct}%` }} />
      </div>
      <div
        className={cn(SLIDER_THUMB_CLASS, "absolute -translate-x-1/2")}
        style={{ left: `${pct}%` }}
      />
    </div>
  );
}

interface SettingRowProps {
  icon: IconFunctionComponent;
  title: string;
  value?: string;
  caption: string;
  children?: React.ReactNode;
}

function SettingRow({
  icon: Icon,
  title,
  value,
  caption,
  children,
}: SettingRowProps) {
  return (
    <div className="flex flex-col rounded-08 p-1.5">
      <div className="flex flex-row items-center gap-2">
        <div className="flex size-5 items-center justify-center text-text-04">
          <Icon size={16} />
        </div>
        <Text font="main-ui-action">{title}</Text>
        <div className="flex-1" />
        {value !== undefined && (
          <Text font="secondary-mono" color="text-04">
            {value}
          </Text>
        )}
      </div>
      {children}
      <Text font="secondary-body" color="text-03">
        {caption}
      </Text>
    </div>
  );
}

interface ModelDetailPaneProps {
  option: LLMOption;
  managers: ModelDetailManagers;
  onBack: () => void;
}

const UNSUPPORTED_SETTING_TOOLTIP =
  "Modifying this setting is not supported for this model.";

function ModelDetailPane({ option, managers, onBack }: ModelDetailPaneProps) {
  // Backend pins temperature to 1 (or omits it) for reasoning models, so the
  // slider is locked at 1. Reasoning is only adjustable when the model
  // supports it.
  const temperatureManager = managers.temperature;
  const reasoningManager = managers.reasoning;
  const temperatureEnabled = !option.supportsReasoning && !!temperatureManager;
  const reasoningEnabled = option.supportsReasoning && !!reasoningManager;

  // Supported stops are always a prefix of ALL_REASONING_STOPS. The slider
  // spans all stops for uniform geometry and clamps input to the max
  // supported index.
  const maxSupportedStop =
    (modelSupportsXhigh(option)
      ? ALL_REASONING_STOPS.length
      : BASE_REASONING_STOPS.length) - 1;

  const [localTemperature, setLocalTemperature] = useState(
    temperatureManager?.temperature ?? 0.5
  );
  // A stored level the model doesn't support (e.g. xhigh after switching
  // models) displays clamped to the highest supported stop.
  const storedStop = ALL_REASONING_STOPS.indexOf(
    reasoningManager?.reasoningEffort ?? "medium"
  );
  const [localEffortStop, setLocalEffortStop] = useState(
    Math.min(
      storedStop === -1 ? ALL_REASONING_STOPS.indexOf("medium") : storedStop,
      maxSupportedStop
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

  const hasContextWindow =
    option.maxInputTokens != null && option.maxInputTokens > 0;
  const contextLabel = hasContextWindow
    ? formatContextWindow(option.maxInputTokens!)
    : "—";
  const contextAxis = hasContextWindow
    ? contextAxisMax(option.maxInputTokens!)
    : 1;

  return (
    <div
      className={cn(
        PANE_HEIGHT_CLASS,
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
        value={contextLabel}
        caption="Tokens limit for each session"
      >
        {hasContextWindow && (
          <>
            <ContextGauge fraction={option.maxInputTokens! / contextAxis} />
            <div className="flex flex-row items-center justify-between">
              <Text font="figure-small-value" color="text-02">
                0
              </Text>
              <Text font="figure-small-value" color="text-04">
                {contextLabel}
              </Text>
              <Text font="figure-small-value" color="text-02">
                {formatContextWindow(contextAxis)}
              </Text>
            </div>
          </>
        )}
      </SettingRow>

      <Disabled
        disabled={!temperatureEnabled}
        tooltip={UNSUPPORTED_SETTING_TOOLTIP}
        tooltipSide="top"
      >
        <SettingRow
          icon={SvgThermometer}
          title="Temperature"
          value={displayTemperature.toFixed(1)}
          caption="How predictable or creative the model should respond"
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
      </Disabled>

      <Disabled
        disabled={!reasoningEnabled}
        tooltip={UNSUPPORTED_SETTING_TOOLTIP}
        tooltipSide="top"
      >
        <SettingRow
          icon={SvgBarChart}
          title="Reasoning Level"
          value={effortLabel}
          caption="How much thinking the model should perform before answering"
        >
          <PaneSlider
            value={localEffortStop}
            min={0}
            max={ALL_REASONING_STOPS.length - 1}
            step={1}
            disabled={!reasoningEnabled}
            onValueChange={(value) =>
              setLocalEffortStop(Math.min(value, maxSupportedStop))
            }
            onValueCommit={(value) => {
              const effort =
                ALL_REASONING_STOPS[Math.min(value, maxSupportedStop)];
              if (effort) reasoningManager?.updateReasoningEffort(effort);
            }}
          />
          <div className="flex flex-row items-center justify-between">
            {ALL_REASONING_STOPS.map((stop, index) => (
              <Disabled
                key={stop}
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
                >
                  {REASONING_STOP_LABELS[stop]}
                </Text>
              </Disabled>
            ))}
          </div>
        </SettingRow>
      </Disabled>
    </div>
  );
}

export interface ModelSelectorContentProps {
  currentModelName?: string;
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
  requiresImageInput,
  onSelect,
  isSelected,
  isDisabled,
  scrollContainerRef: externalScrollRef,
  includeGlobalDefault = false,
  modelDetail,
}: ModelSelectorContentProps) {
  const [detailOption, setDetailOption] = useState<LLMOption | null>(null);
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
    <div className={cn(PANE_HEIGHT_CLASS, "flex w-full flex-col gap-1")}>
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
                    <Section
                      key="single-provider"
                      gap={0.25}
                      alignItems="stretch"
                    >
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
                    // null children render as PopoverMenu divider lines.
                    return groupIndex > 0 ? [null, collapsible] : [collapsible];
                  })),
        ]}
      </PopoverMenu>
    </div>
  );
}
