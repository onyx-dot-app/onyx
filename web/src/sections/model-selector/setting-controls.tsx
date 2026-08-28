"use client";

import * as SliderPrimitive from "@radix-ui/react-slider";
import { Text, Tooltip } from "@opal/components";
import { Section } from "@opal/layouts";
import { cn } from "@opal/utils";
import type { IconFunctionComponent } from "@opal/types";
import { Disabled } from "@opal/core";
import { ReasoningEffortOverride } from "@/lib/languageModels/types";

/** The levels every reasoning model supports, in ascending order. */
const BASE_REASONING_STOPS: ReasoningEffortOverride[] = [
  "off",
  "low",
  "medium",
  "high",
];

/** Every stop the slider renders. Unsupported stops are greyed, never hidden. */
export const ALL_REASONING_STOPS: ReasoningEffortOverride[] = [
  ...BASE_REASONING_STOPS,
  "xhigh",
];

/** Message keys under the `chat.modelSelector` namespace, one per stop. */
export const REASONING_STOP_LABEL_KEYS = {
  off: "reasoningLevel.off.label",
  low: "reasoningLevel.low.label",
  medium: "reasoningLevel.medium.label",
  high: "reasoningLevel.high.label",
  xhigh: "reasoningLevel.xhigh.label",
} as const satisfies Record<ReasoningEffortOverride, string>;

/** Where an unset reasoning setting parks: the backend resolves AUTO to medium. */
export const UNSET_REASONING_STOP = ALL_REASONING_STOPS.indexOf("medium");

/** Highest supported stop. Nothing from an older backend means the base set. */
export function maxReasoningStop(
  supported: ReasoningEffortOverride[] | undefined
): number {
  if (!supported) return BASE_REASONING_STOPS.length - 1;
  return Math.max(
    -1,
    ...supported.map((effort) => ALL_REASONING_STOPS.indexOf(effort))
  );
}

export function reasoningStopIndex(
  effort: ReasoningEffortOverride | null | undefined
): number {
  return effort ? ALL_REASONING_STOPS.indexOf(effort) : -1;
}

/** Highest stop a user may request: model capability, narrowed by the admin cap. */
export function cappedReasoningStop(
  capabilityStop: number,
  cap: ReasoningEffortOverride | null | undefined
): number {
  const capStop = reasoningStopIndex(cap);
  return capStop >= 0 ? Math.min(capabilityStop, capStop) : capabilityStop;
}

export function formatContextWindow(tokens: number): string {
  if (tokens >= 1_000_000)
    return `${(tokens / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  return tokens >= 1000 ? `${Math.round(tokens / 1000)}K` : `${tokens}`;
}

const SLIDER_THUMB_CLASS =
  "block size-3 rounded-full bg-background-neutral-00 shadow-[0_0_2px_1px_rgba(0,0,0,0.15)] focus:outline-none";
const SLIDER_TRACK_CLASS =
  "h-1.5 w-full overflow-hidden rounded bg-background-tint-02";
const SLIDER_FILL_CLASS = "h-full bg-theme-primary-05";

interface PaneSliderProps {
  value: number;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  /** 16px-tall variant matching the mock's popover sliders. */
  compact?: boolean;
  onValueChange: (value: number) => void;
  onValueCommit: (value: number) => void;
}

export function PaneSlider({
  value,
  min,
  max,
  step,
  disabled,
  compact,
  onValueChange,
  onValueCommit,
}: PaneSliderProps) {
  return (
    <SliderPrimitive.Root
      className={cn(
        "relative flex w-full cursor-pointer touch-none select-none items-center",
        compact ? "h-4" : "h-7"
      )}
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

interface SettingRowProps {
  icon: IconFunctionComponent;
  title: string;
  value?: string;
  /** Shown when hovering the value readout. */
  valueTooltip?: string;
  caption: string;
  disabled?: boolean;
  /** Shown when hovering the row while disabled. */
  disabledTooltip?: string;
  children?: React.ReactNode;
}

export function SettingRow({
  icon: Icon,
  title,
  value,
  valueTooltip,
  caption,
  disabled = false,
  disabledTooltip,
  children,
}: SettingRowProps) {
  return (
    <Disabled disabled={disabled} tooltip={disabledTooltip} tooltipSide="top">
      <Section
        alignItems="stretch"
        height="auto"
        gap={0}
        padding={1.5}
        className="rounded-08"
      >
        <Section
          flexDirection="row"
          justifyContent="between"
          height="auto"
          gap={2}
        >
          <Section flexDirection="row" width="fit" height="auto" gap={2}>
            <Section width={1.25} height={1.25} className="text-text-04">
              <Icon size={16} />
            </Section>
            <Text font="main-ui-action">{title}</Text>
          </Section>
          {value !== undefined && (
            <Tooltip tooltip={valueTooltip} side="top">
              <Text font="secondary-mono" color="text-04">
                {value}
              </Text>
            </Tooltip>
          )}
        </Section>
        {children}
        <Section alignItems="stretch" height="auto" className="mt-2">
          <Text font="secondary-body" color="text-03">
            {caption}
          </Text>
        </Section>
      </Section>
    </Disabled>
  );
}
