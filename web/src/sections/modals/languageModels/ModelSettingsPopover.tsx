"use client";

import { useState } from "react";
import { Button, Popover, Text, Tooltip } from "@opal/components";
import { SvgBarChart, SvgCode, SvgSliders, SvgThermometer } from "@opal/icons";
import { Section } from "@opal/layouts";
import { Disabled } from "@opal/core";
import type { IconFunctionComponent } from "@opal/types";
import { isAnthropic } from "@/lib/languageModels/svc";
import type { ModelConfiguration } from "@/lib/languageModels/types";
import {
  ALL_REASONING_STOPS,
  PaneSlider,
  REASONING_STOP_LABELS,
  UNKNOWN_CONTEXT_TOOLTIP,
  formatContextWindow,
  maxReasoningStop,
  reasoningStopIndex,
} from "@/sections/model-selector/setting-controls";

const PINNED_TEMPERATURE_TOOLTIP =
  "Reasoning models always run at temperature 1.";

/** Where an unset slider parks: the value the backend would apply anyway. */
const UNSET_REASONING_STOP = ALL_REASONING_STOPS.indexOf("medium");
const UNSET_TEMPERATURE = 0;

const TEMPERATURE_MARKS = ["Deterministic", "Balanced", "Creative"];

export type ModelSettingsPatch = Partial<
  Pick<
    ModelConfiguration,
    "reasoning_effort_max" | "reasoning_effort_default" | "temperature_default"
  >
>;

interface ModelSettingsPopoverProps {
  model: ModelConfiguration;
  onChange: (patch: ModelSettingsPatch) => void;
}

interface SectionHeaderProps {
  icon: IconFunctionComponent;
  title: string;
  caption: string;
  rightValue?: string;
  rightValueTooltip?: string;
}

/** Mock spec: 8px padding, 20px icon box, 4px gap, 2px text insets. */
function SectionHeader({
  icon: Icon,
  title,
  caption,
  rightValue,
  rightValueTooltip,
}: SectionHeaderProps) {
  // raw-ok: mock needs 2px text insets and a flex-1/min-w-0 column, and Section silences px-*
  return (
    <div className="flex w-full gap-1 p-2">
      <div className="flex size-5 shrink-0 items-center justify-center p-0.5 text-text-04">
        <Icon size={16} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex w-full items-start gap-1">
          <div className="flex min-h-5 min-w-0 flex-1 flex-col justify-center px-0.5">
            <Text font="main-ui-action" color="text-04" nowrap>
              {title}
            </Text>
          </div>
          {rightValue !== undefined && (
            <div className="flex min-h-5 items-center p-0.5">
              <Tooltip tooltip={rightValueTooltip} side="top">
                <Text font="secondary-mono" color="text-04" nowrap>
                  {rightValue}
                </Text>
              </Tooltip>
            </div>
          )}
        </div>
        <div className="px-0.5">
          <Text font="secondary-body" color="text-03">
            {caption}
          </Text>
        </div>
      </div>
    </div>
  );
}

interface PolicySliderProps {
  label: string;
  value: number;
  max: number;
  step: number;
  marks: string[];
  activeMark: number;
  onChange: (value: number) => void;
}

/** Mock spec: 32px left inset, 8px right, 16px label line, 28px slider. */
function PolicySlider({
  label,
  value,
  max,
  step,
  marks,
  activeMark,
  onChange,
}: PolicySliderProps) {
  // raw-ok: mock needs asymmetric pl-8/pr-2, and Section silences p-* utilities
  return (
    <div className="w-full pl-8 pr-2">
      <div className="px-0.5">
        <Text font="secondary-action" color="text-03" nowrap>
          {label}
        </Text>
      </div>
      <div className="p-0.5">
        <PaneSlider
          compact
          value={value}
          min={0}
          max={max}
          step={step}
          onValueChange={onChange}
          onValueCommit={onChange}
        />
        <div className="flex w-full items-center justify-between">
          {marks.map((mark, index) => (
            <Text
              key={mark}
              font="figure-small-value"
              color={index === activeMark ? "text-04" : "text-02"}
              nowrap
            >
              {mark}
            </Text>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ModelSettingsPopover({
  model,
  onChange,
}: ModelSettingsPopoverProps) {
  const [open, setOpen] = useState(false);

  const supportedStop = maxReasoningStop(model.supported_reasoning_efforts);
  // No supported levels means the model takes no effort parameter at all.
  const showReasoning = model.supports_reasoning && supportedStop >= 0;
  // The backend pins reasoning models to 1, so the control renders disabled.
  const temperatureDisabled = model.supports_reasoning;
  const maxTemperature = isAnthropic(model.vendor ?? "", model.name) ? 1 : 2;

  const maxStop = reasoningStopIndex(model.reasoning_effort_max);
  const rawDefaultStop = reasoningStopIndex(model.reasoning_effort_default);
  // Capability bounds the stored cap too, in case it shrank after the save.
  const effectiveMaxStop = Math.min(
    maxStop >= 0 ? maxStop : supportedStop,
    supportedStop
  );
  const defaultStop =
    rawDefaultStop >= 0 ? Math.min(rawDefaultStop, effectiveMaxStop) : -1;

  const reasoningMarks = ALL_REASONING_STOPS.slice(0, supportedStop + 1).map(
    (stop) => REASONING_STOP_LABELS[stop]
  );
  const temperature = model.temperature_default ?? UNSET_TEMPERATURE;
  const temperatureMark = Math.min(
    Math.floor((temperature / maxTemperature) * TEMPERATURE_MARKS.length),
    TEMPERATURE_MARKS.length - 1
  );

  const capabilities = [
    model.supports_reasoning && "reasoning",
    model.supports_image_input && "multi-modal",
  ].filter(Boolean);

  function setMax(stop: number) {
    const newMaxStop = Math.min(stop, supportedStop);
    const effort = ALL_REASONING_STOPS[newMaxStop];
    if (!effort) return;
    const patch: ModelSettingsPatch = { reasoning_effort_max: effort };
    // The API rejects a default above the max. Compare the raw stored default,
    // not the clamped display value, so a stale higher default gets rewritten.
    if (rawDefaultStop > newMaxStop) {
      patch.reasoning_effort_default = effort;
    }
    onChange(patch);
  }

  function setDefault(stop: number) {
    const effort = ALL_REASONING_STOPS[Math.min(stop, effectiveMaxStop)];
    if (effort) onChange({ reasoning_effort_default: effort });
  }

  return (
    // A modal popover keeps clicks and focus inside it away from the host
    // dialog's dismiss and focus-trap layers, without portaling into the
    // dialog box, which gave the dialog its own scrollbar.
    <Popover open={open} onOpenChange={setOpen} modal>
      <Popover.Trigger asChild>
        <Button
          icon={SvgSliders}
          prominence="internal"
          size="sm"
          tooltip="Model Settings"
          onClick={(e: React.MouseEvent) => e.stopPropagation()}
        />
      </Popover.Trigger>
      <Popover.Content width="fit" align="end">
        {/* raw-ok: scroll shell, Popover.Content clips overflow when the viewport is short */}
        <div className="min-h-0 w-full overflow-y-auto">
          <Section alignItems="stretch" width={17} height="auto" gap={0.25}>
            {/* raw-ok: mock header needs 10px/8px asymmetric padding, and Section silences px-* */}
            <div className="flex w-full flex-col justify-center px-2.5 py-2">
              <Text font="main-ui-body" color="text-02" nowrap>
                {model.custom_display_name || model.display_name || model.name}
              </Text>
              <Text font="secondary-body" color="text-02">
                {capabilities.length ? capabilities.join(", ") : "chat"}
              </Text>
            </div>

            <SectionHeader
              icon={SvgCode}
              title="Context Window"
              caption="Tokens limit for each session"
              rightValue={
                model.max_input_tokens
                  ? formatContextWindow(model.max_input_tokens)
                  : "\u2014"
              }
              rightValueTooltip={
                model.max_input_tokens ? undefined : UNKNOWN_CONTEXT_TOOLTIP
              }
            />

            {showReasoning && (
              <Section
                alignItems="stretch"
                height="auto"
                gap={0.375}
                className="mb-1.5"
              >
                <SectionHeader
                  icon={SvgBarChart}
                  title="Reasoning Level"
                  caption="How much thinking the model should perform before answering"
                />
                <PolicySlider
                  label="Max Level"
                  value={effectiveMaxStop}
                  max={supportedStop}
                  step={1}
                  marks={reasoningMarks}
                  activeMark={effectiveMaxStop}
                  onChange={setMax}
                />
                <PolicySlider
                  label="Default"
                  value={defaultStop >= 0 ? defaultStop : UNSET_REASONING_STOP}
                  max={effectiveMaxStop}
                  step={1}
                  marks={reasoningMarks}
                  activeMark={
                    defaultStop >= 0 ? defaultStop : UNSET_REASONING_STOP
                  }
                  onChange={setDefault}
                />
              </Section>
            )}

            <Disabled
              disabled={temperatureDisabled}
              tooltip={PINNED_TEMPERATURE_TOOLTIP}
              tooltipSide="top"
            >
              <Section
                alignItems="stretch"
                height="auto"
                gap={0.375}
                className="mb-1.5"
              >
                <SectionHeader
                  icon={SvgThermometer}
                  title="Temperature"
                  caption="How predictable or creative the model should respond"
                />
                <PolicySlider
                  label="Default"
                  value={temperatureDisabled ? 1 : temperature}
                  max={maxTemperature}
                  step={0.1}
                  marks={TEMPERATURE_MARKS}
                  activeMark={temperatureMark}
                  onChange={(v) => onChange({ temperature_default: v })}
                />
              </Section>
            </Disabled>
          </Section>
        </div>
      </Popover.Content>
    </Popover>
  );
}
