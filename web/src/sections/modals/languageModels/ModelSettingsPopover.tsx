"use client";

import { useCallback, useState } from "react";
import { Button, Popover, Text } from "@opal/components";
import { SvgBarChart, SvgCode, SvgSliders, SvgThermometer } from "@opal/icons";
import { Section } from "@opal/layouts";
import { isAnthropic } from "@/lib/languageModels/svc";
import type {
  ModelConfiguration,
  ReasoningEffortOverride,
} from "@/lib/languageModels/types";
import {
  ALL_REASONING_STOPS,
  PaneSlider,
  REASONING_STOP_LABELS,
  SettingRow,
  UNKNOWN_CONTEXT_TOOLTIP,
  formatContextWindow,
  maxReasoningStop,
  reasoningStopIndex,
} from "@/sections/model-selector/setting-controls";

/** Where an unset slider parks: the value the backend would apply anyway. */
const UNSET_REASONING_STOP = ALL_REASONING_STOPS.indexOf("medium");
const UNSET_TEMPERATURE = 0;

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

function ResetToAuto({ onClick }: { onClick: () => void }) {
  return (
    <Section flexDirection="row" justifyContent="end" height="auto">
      <Button prominence="tertiary" onClick={onClick}>
        Reset to auto
      </Button>
    </Section>
  );
}

export function ModelSettingsPopover({
  model,
  onChange,
}: ModelSettingsPopoverProps) {
  const [open, setOpen] = useState(false);
  // Portal into the dialog. Left on body, the popover sits outside the modal's
  // focus scope and a click inside it reads as a click outside the modal.
  const [container, setContainer] = useState<HTMLElement | null>(null);
  const anchorRef = useCallback((el: HTMLElement | null) => {
    setContainer(el?.closest<HTMLElement>('[role="dialog"]') ?? null);
  }, []);

  const supportedStop = maxReasoningStop(model.supported_reasoning_efforts);
  // No supported levels means the model takes no effort parameter at all.
  const showReasoning = model.supports_reasoning && supportedStop >= 0;
  // The backend pins reasoning models to 1, so a default would never apply.
  const showTemperature = !model.supports_reasoning;
  const maxTemperature = isAnthropic(model.vendor ?? "", model.name) ? 1 : 2;

  const maxStop = reasoningStopIndex(model.reasoning_effort_max);
  const rawDefaultStop = reasoningStopIndex(model.reasoning_effort_default);
  // Capability bounds the stored cap too, in case the model's supported levels
  // shrank after the cap was saved.
  const effectiveMaxStop = Math.min(
    maxStop >= 0 ? maxStop : supportedStop,
    supportedStop
  );
  // Read back clamped as well as rendered clamped, so the label never advertises
  // a level the model lost since the value was saved.
  const defaultStop =
    rawDefaultStop >= 0 ? Math.min(rawDefaultStop, effectiveMaxStop) : -1;

  function setMax(stop: number) {
    const effort = ALL_REASONING_STOPS[Math.min(stop, supportedStop)];
    if (!effort) return;
    const patch: ModelSettingsPatch = { reasoning_effort_max: effort };
    // The API rejects a default above the max, so keep the pair consistent.
    if (defaultStop > Math.min(stop, supportedStop)) {
      patch.reasoning_effort_default = effort;
    }
    onChange(patch);
  }

  function setDefault(stop: number) {
    const effort = ALL_REASONING_STOPS[Math.min(stop, effectiveMaxStop)];
    if (effort) onChange({ reasoning_effort_default: effort });
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button
          ref={anchorRef}
          icon={SvgSliders}
          prominence="tertiary"
          tooltip="Model Settings"
          onClick={(e: React.MouseEvent) => e.stopPropagation()}
        />
      </Popover.Trigger>
      <Popover.Content width="md" container={container} align="end">
        <Section alignItems="stretch" height="auto" gap={1} padding={1}>
          <Section alignItems="stretch" height="auto" gap={0} padding={1.5}>
            <Text font="main-ui-action">
              {model.custom_display_name || model.display_name || model.name}
            </Text>
            <Text font="secondary-body" color="text-03">
              {model.supports_reasoning ? "Reasoning model" : "Chat model"}
            </Text>
          </Section>

          <SettingRow
            icon={SvgCode}
            title="Context Window"
            value={
              model.max_input_tokens
                ? formatContextWindow(model.max_input_tokens)
                : "—"
            }
            valueTooltip={
              model.max_input_tokens ? undefined : UNKNOWN_CONTEXT_TOOLTIP
            }
            caption="How much text this model can consider at once."
          />

          {showReasoning && (
            <>
              <SettingRow
                icon={SvgBarChart}
                title="Reasoning Level, Max"
                value={
                  maxStop >= 0
                    ? REASONING_STOP_LABELS[
                        ALL_REASONING_STOPS[effectiveMaxStop]!
                      ]
                    : "Auto"
                }
                caption="The most reasoning a user can request for this model."
              >
                <PaneSlider
                  value={effectiveMaxStop}
                  min={0}
                  max={supportedStop}
                  step={1}
                  onValueChange={setMax}
                  onValueCommit={setMax}
                />
              </SettingRow>

              <SettingRow
                icon={SvgBarChart}
                title="Reasoning Level, Default"
                value={
                  defaultStop >= 0
                    ? REASONING_STOP_LABELS[ALL_REASONING_STOPS[defaultStop]!]
                    : "Auto"
                }
                caption="Where a chat starts when the user has not chosen a level."
              >
                <PaneSlider
                  value={Math.min(
                    defaultStop >= 0 ? defaultStop : UNSET_REASONING_STOP,
                    effectiveMaxStop
                  )}
                  min={0}
                  max={effectiveMaxStop}
                  step={1}
                  onValueChange={setDefault}
                  onValueCommit={setDefault}
                />
              </SettingRow>

              <ResetToAuto
                onClick={() =>
                  onChange({
                    reasoning_effort_max: null,
                    reasoning_effort_default: null,
                  })
                }
              />
            </>
          )}

          {showTemperature && (
            <>
              <SettingRow
                icon={SvgThermometer}
                title="Temperature, Default"
                value={
                  model.temperature_default != null
                    ? model.temperature_default.toFixed(1)
                    : "Auto"
                }
                caption="Lower is more deterministic, higher is more creative."
              >
                <PaneSlider
                  value={model.temperature_default ?? UNSET_TEMPERATURE}
                  min={0}
                  max={maxTemperature}
                  step={0.1}
                  onValueChange={(v) => onChange({ temperature_default: v })}
                  onValueCommit={(v) => onChange({ temperature_default: v })}
                />
              </SettingRow>

              <ResetToAuto
                onClick={() => onChange({ temperature_default: null })}
              />
            </>
          )}
        </Section>
      </Popover.Content>
    </Popover>
  );
}
