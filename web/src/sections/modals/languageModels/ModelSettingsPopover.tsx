"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Popover, Text, Tooltip } from "@opal/components";
import { SvgBarChart, SvgCode, SvgSliders, SvgThermometer } from "@opal/icons";
import { ContentAction, Section } from "@opal/layouts";
import { Disabled } from "@opal/core";
import type { IconFunctionComponent } from "@opal/types";
import { isAnthropic } from "@/lib/languageModels/svc";
import type { ModelConfiguration } from "@/lib/languageModels/types";
import { modelDisplayName } from "@/lib/languageModels/utils";
import {
  ALL_REASONING_STOPS,
  PaneSlider,
  REASONING_STOP_LABEL_KEYS,
  formatContextWindow,
  maxReasoningStop,
  reasoningStopIndex,
} from "@/sections/model-selector/setting-controls";

/** Where an unset slider parks: the backend default (medium reasoning,
 *  GEN_AI_TEMPERATURE for temperature). */
const UNSET_REASONING_STOP = ALL_REASONING_STOPS.indexOf("medium");
const UNSET_TEMPERATURE = 0;

const TEMPERATURE_MARK_COUNT = 3;

export type ModelSettingsPatch = Partial<
  Pick<
    ModelConfiguration,
    "reasoning_effort_max" | "reasoning_effort_default" | "temperature_default"
  >
>;

/** The subset of a model configuration the popover reads. */
export type ModelSettingsModel = Pick<
  ModelConfiguration,
  | "name"
  | "display_name"
  | "custom_display_name"
  | "vendor"
  | "max_input_tokens"
  | "supports_reasoning"
  | "supports_image_input"
  | "supported_reasoning_efforts"
  | "reasoning_effort_max"
  | "reasoning_effort_default"
  | "temperature_default"
>;

interface ModelSettingsPopoverProps {
  model: ModelSettingsModel;
  onChange: (patch: ModelSettingsPatch) => void;
  /** Reports open state so a hover-revealed trigger can stay visible. */
  onOpenChange?: (open: boolean) => void;
}

interface SectionHeaderProps {
  icon: IconFunctionComponent;
  title: string;
  caption: string;
  rightValue?: string;
  rightValueTooltip?: string;
}

/** The mock's section header is the design system's Content component, so
 *  ContentAction renders it. Outer spacing comes from margins, Section
 *  silences padding utilities. */
function SectionHeader({
  icon,
  title,
  caption,
  rightValue,
  rightValueTooltip,
}: SectionHeaderProps) {
  return (
    <Section
      alignItems="stretch"
      width="auto"
      height="auto"
      className="mx-2 mb-0.5 mt-2"
    >
      <ContentAction
        sizePreset="main-ui"
        variant="section"
        icon={icon}
        title={title}
        description={caption}
        padding={0}
        rightChildren={
          rightValue !== undefined ? (
            <Tooltip tooltip={rightValueTooltip} side="top">
              <Text font="secondary-mono" color="text-04" nowrap>
                {rightValue}
              </Text>
            </Tooltip>
          ) : undefined
        }
      />
    </Section>
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

/** Mock spec: 32px left inset, 8px right, 16px label line, 28px slider.
 *  Insets are margins because Section silences padding utilities. */
function PolicySlider({
  label,
  value,
  max,
  step,
  marks,
  activeMark,
  onChange,
}: PolicySliderProps) {
  return (
    <Section
      alignItems="stretch"
      width="auto"
      height="auto"
      gap={0}
      className="ml-8 mr-2"
    >
      <Section alignItems="start" width="auto" height="auto" className="mx-0.5">
        <Text font="secondary-action" color="text-03" nowrap>
          {label}
        </Text>
      </Section>
      <Section alignItems="stretch" height="auto" padding={0.5}>
        <PaneSlider
          compact
          value={value}
          min={0}
          max={max}
          step={step}
          onValueChange={onChange}
          onValueCommit={onChange}
        />
        <Section flexDirection="row" justifyContent="between" height={0.75}>
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
        </Section>
      </Section>
    </Section>
  );
}

export function ModelSettingsPopover({
  model,
  onChange,
  onOpenChange,
}: ModelSettingsPopoverProps) {
  const t = useTranslations("admin.languageModels.modals");
  // The reasoning, context and temperature vocabulary is shared with the chat
  // model selector, so both surfaces read the same messages.
  const tModelSelector = useTranslations("chat.modelSelector");
  const [open, setOpen] = useState(false);
  function handleOpenChange(next: boolean) {
    setOpen(next);
    onOpenChange?.(next);
  }

  const supportedStop = maxReasoningStop(model.supported_reasoning_efforts);
  // No supported levels means the model takes no effort parameter at all.
  const showReasoning = model.supports_reasoning && supportedStop >= 0;
  // The backend pins reasoning models to 1, so the control renders disabled.
  const temperatureDisabled = model.supports_reasoning;
  const maxTemperature = isAnthropic(model.vendor ?? "", model.name) ? 1 : 2;

  const maxStop = reasoningStopIndex(model.reasoning_effort_max);
  const rawDefaultStop = reasoningStopIndex(model.reasoning_effort_default);
  // Capability bounds the stored cap too, in case it shrank after the save.
  const effectiveMaxStop =
    maxStop >= 0 ? Math.min(maxStop, supportedStop) : supportedStop;
  const defaultStop =
    rawDefaultStop >= 0 ? Math.min(rawDefaultStop, effectiveMaxStop) : -1;
  // An unset default parks where the backend resolves AUTO: medium, bounded
  // by the cap.
  const defaultSliderStop =
    defaultStop >= 0
      ? defaultStop
      : Math.min(UNSET_REASONING_STOP, effectiveMaxStop);

  const reasoningMarks = ALL_REASONING_STOPS.slice(0, supportedStop + 1).map(
    (stop) => tModelSelector(REASONING_STOP_LABEL_KEYS[stop])
  );
  const temperatureMarks = [
    tModelSelector("temperature.deterministic.label"),
    tModelSelector("temperature.balanced.label"),
    tModelSelector("temperature.creative.label"),
  ];
  const temperature = model.temperature_default ?? UNSET_TEMPERATURE;
  const temperatureMark = Math.min(
    Math.floor((temperature / maxTemperature) * TEMPERATURE_MARK_COUNT),
    TEMPERATURE_MARK_COUNT - 1
  );

  const capabilities = [
    model.supports_reasoning && t("modelSettings.capabilities.reasoning.label"),
    model.supports_image_input &&
      t("modelSettings.capabilities.multiModal.label"),
  ].filter((c): c is string => Boolean(c));

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
    // modal keeps clicks and focus inside the popover away from the host
    // dialog's dismiss and focus-trap layers. Portaling into the dialog
    // instead would give the dialog its own scrollbar.
    <Popover open={open} onOpenChange={handleOpenChange} modal>
      <Popover.Trigger asChild>
        <Button
          icon={SvgSliders}
          prominence="internal"
          size="sm"
          tooltip={t("modelSettings.trigger.tooltip")}
          onClick={(e: React.MouseEvent) => e.stopPropagation()}
        />
      </Popover.Trigger>
      <Popover.Content width="fit" align="end">
        <Section alignItems="stretch" width={17} height="auto" gap={0.25}>
          <Section
            alignItems="start"
            width="auto"
            height="auto"
            gap={0}
            className="mx-2.5 my-2"
          >
            <Text font="main-ui-body" color="text-02" nowrap>
              {modelDisplayName(model)}
            </Text>
            <Text font="secondary-body" color="text-02">
              {capabilities.length
                ? capabilities.join(", ")
                : t("modelSettings.capabilities.chat.label")}
            </Text>
          </Section>

          <SectionHeader
            icon={SvgCode}
            title={tModelSelector("contextWindow.row.title")}
            caption={tModelSelector("contextWindow.row.caption")}
            rightValue={
              model.max_input_tokens
                ? formatContextWindow(model.max_input_tokens)
                : "\u2014"
            }
            rightValueTooltip={
              model.max_input_tokens
                ? undefined
                : tModelSelector("contextWindow.unknown.tooltip")
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
                title={tModelSelector("reasoningLevel.row.title")}
                caption={tModelSelector("reasoningLevel.row.caption")}
              />
              <PolicySlider
                label={t("modelSettings.reasoningLevel.maxSlider.label")}
                value={effectiveMaxStop}
                max={supportedStop}
                step={1}
                marks={reasoningMarks}
                activeMark={effectiveMaxStop}
                onChange={setMax}
              />
              <PolicySlider
                label={t("modelSettings.reasoningLevel.defaultSlider.label")}
                value={defaultSliderStop}
                max={supportedStop}
                step={1}
                marks={reasoningMarks}
                activeMark={defaultSliderStop}
                onChange={setDefault}
              />
            </Section>
          )}

          <Disabled
            disabled={temperatureDisabled}
            tooltip={t("modelSettings.temperature.pinned.tooltip")}
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
                title={tModelSelector("temperature.row.title")}
                caption={tModelSelector("temperature.row.caption")}
              />
              <PolicySlider
                label={t("modelSettings.temperature.defaultSlider.label")}
                value={temperatureDisabled ? 1 : temperature}
                max={maxTemperature}
                step={0.1}
                marks={temperatureMarks}
                activeMark={temperatureMark}
                onChange={(v) => onChange({ temperature_default: v })}
              />
            </Section>
          </Disabled>
        </Section>
      </Popover.Content>
    </Popover>
  );
}
