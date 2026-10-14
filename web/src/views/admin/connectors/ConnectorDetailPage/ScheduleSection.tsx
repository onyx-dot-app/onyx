"use client";

import { useEffect, useRef, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { mutate } from "swr";
import { Card, Collapsible, InputNumber, Text } from "@opal/components";
import { InputHorizontal, Section, toast } from "@opal/layouts";
import { markdown } from "@opal/utils";
import type { RichStr } from "@opal/types";
import type { CCPairFullInfo } from "@/lib/connectors/types";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { updateConnectorCredentialPairProperty } from "@/lib/connector";
import {
  MAX_PRUNE_FREQ_HOURS,
  MAX_REFRESH_FREQ_MINUTES,
  MIN_PRUNE_FREQ_HOURS,
  MIN_REFRESH_FREQ_MINUTES,
} from "@/lib/connectors/connectors";

interface FrequencyFieldProps {
  id: string;
  title: string | RichStr;
  description: string | RichStr;
  value: number | null;
  min: number;
  max: number;
  decimalPlaces?: number;
  suffix: string;
  /** Marks the field optional in its label. */
  optional?: boolean;
  disabled: boolean;
  /** Resolves to whether the server stored the value. Never rejects. */
  onSave: (value: number) => Promise<boolean>;
}

/** One schedule frequency. It saves when the field loses focus. A blank or out of range value is dropped. */
function FrequencyField({
  id,
  title,
  description,
  value,
  min,
  max,
  decimalPlaces,
  suffix,
  optional = false,
  disabled,
  onSave,
}: FrequencyFieldProps) {
  const [draft, setDraft] = useState<number | null>(value);
  // Read on blur, which fires in the same event as the input's last change.
  const draftRef = useRef<number | null>(value);
  function change(next: number | null) {
    draftRef.current = next;
    setDraft(next);
  }
  useEffect(() => change(value), [value]);

  async function commit() {
    const next = draftRef.current;
    // The input restores a blank field itself.
    if (next === null) return;
    if (next < min || next > max) {
      change(value);
      return;
    }
    if (next === value) return;
    if (!(await onSave(next))) change(value);
  }

  return (
    <InputHorizontal
      withLabel={id}
      title={title}
      description={description}
      suffix={optional ? "optional" : undefined}
      disabled={disabled}
      fillInput
      center
    >
      {/* Blur bubbles up from the input. */}
      <Section height="fit" alignItems="stretch" onBlur={() => void commit()}>
        <InputNumber
          id={id}
          value={draft}
          onChange={change}
          min={min}
          max={max}
          decimalPlaces={decimalPlaces}
          suffix={suffix}
          disabled={disabled}
          allowEmpty={false}
        />
      </Section>
    </InputHorizontal>
  );
}

export interface ScheduleSectionProps {
  ccPair: CCPairFullInfo;
  /** The schedule can be changed in place. */
  editable: boolean;
}

/** When the connector refreshes and prunes, and the date it indexes from. */
export default function ScheduleSection({
  ccPair,
  editable,
}: ScheduleSectionProps) {
  const t = useTranslations("admin.connector.schedule");
  const tFields = useTranslations("admin.connectorsList.scheduled");
  const tToasts = useTranslations("admin.connector.toasts");
  const tDuration = useTranslations("admin.connector.advancedConfig.duration");
  const format = useFormatter();
  const { refresh_freq, prune_freq, check_freq, indexing_start } =
    ccPair.connector;
  const refreshMinutes =
    refresh_freq === null ? null : Math.round(refresh_freq / 60);
  const pruneHours =
    prune_freq === null ? null : Number((prune_freq / 3600).toFixed(3));
  const checkHours =
    check_freq === null ? null : Number((check_freq / 3600).toFixed(3));

  // Whole hours read as hours, whole days as days.
  function minutesLabel(minutes: number): string {
    return minutes >= 60 && minutes % 60 === 0
      ? tDuration("hours", { count: minutes / 60 })
      : tDuration("minutes", { count: minutes });
  }
  function hoursLabel(hours: number): string {
    if (hours < 1) {
      return tDuration("minutes", { count: Math.round(hours * 60) });
    }
    const whole = Math.round(hours);
    return whole >= 24 && whole % 24 === 0
      ? tDuration("days", { count: whole / 24 })
      : tDuration("hours", { count: whole });
  }

  async function save(
    name: "refresh_frequency" | "pruning_frequency" | "check_frequency",
    seconds: number,
    successKey:
      | "refreshFrequencyUpdated"
      | "pruningFrequencyUpdated"
      | "checkFrequencyUpdated",
    failureKey:
      | "refreshFrequencyUpdateFailed"
      | "pruningFrequencyUpdateFailed"
      | "checkFrequencyUpdateFailed"
  ): Promise<boolean> {
    let stored = false;
    try {
      const response = await updateConnectorCredentialPairProperty(
        ccPair.id,
        name,
        String(Math.round(seconds))
      );
      stored = response.ok;
    } catch {
      stored = false;
    }
    if (!stored) {
      toast.error(tToasts(failureKey));
      return false;
    }
    await mutate(buildCCPairInfoUrl(ccPair.id));
    toast.success(tToasts(successKey));
    return true;
  }

  const summary = format.list(
    [
      refreshMinutes === null
        ? null
        : t("refresh", { every: minutesLabel(refreshMinutes) }),
      pruneHours === null
        ? null
        : t("prune", { every: hoursLabel(pruneHours) }),
      checkHours === null
        ? null
        : t("checks", { every: hoursLabel(checkHours) }),
    ].filter((part) => part !== null),
    { type: "unit" }
  );

  return (
    <Collapsible
      title={tFields("title")}
      description={summary ? markdown(summary) : undefined}
      defaultOpen={false}
    >
      <Card border="solid" rounding={4} padding={4}>
        <Section alignItems="stretch" gap={4} height="fit">
          <FrequencyField
            id="refreshFreq"
            title={tFields("refreshFrequency.title")}
            description={tFields("refreshFrequency.description")}
            value={refreshMinutes}
            min={MIN_REFRESH_FREQ_MINUTES}
            max={MAX_REFRESH_FREQ_MINUTES}
            suffix={tFields("units.minutes")}
            disabled={!editable}
            onSave={(minutes) =>
              save(
                "refresh_frequency",
                minutes * 60,
                "refreshFrequencyUpdated",
                "refreshFrequencyUpdateFailed"
              )
            }
          />
          <FrequencyField
            id="pruneFreq"
            title={tFields("pruneFrequency.title")}
            description={tFields("pruneFrequency.description")}
            value={pruneHours}
            min={MIN_PRUNE_FREQ_HOURS}
            max={MAX_PRUNE_FREQ_HOURS}
            decimalPlaces={3}
            suffix={tFields("units.hours")}
            disabled={!editable}
            onSave={(hours) =>
              save(
                "pruning_frequency",
                hours * 3600,
                "pruningFrequencyUpdated",
                "pruningFrequencyUpdateFailed"
              )
            }
          />
          {/* Only a source with checks of its own can schedule them. Blank until set: they run only on request by default. */}
          {ccPair.has_named_checks && (
            <FrequencyField
              id="checkFreq"
              title={tFields("checkFrequency.title")}
              description={tFields("checkFrequency.description")}
              value={checkHours}
              min={MIN_PRUNE_FREQ_HOURS}
              max={MAX_PRUNE_FREQ_HOURS}
              decimalPlaces={3}
              suffix={tFields("units.hours")}
              optional
              disabled={!editable}
              onSave={(hours) =>
                save(
                  "check_frequency",
                  hours * 3600,
                  "checkFrequencyUpdated",
                  "checkFrequencyUpdateFailed"
                )
              }
            />
          )}
          <InputHorizontal
            title={tFields("indexingStart.title")}
            description={tFields("indexingStart.description")}
            suffix="optional"
            fillInput
            center
          >
            {/* Read-only here. The connector form changes it. */}
            <Text font="main-ui-body" color="text-04">
              {indexing_start === null
                ? tFields("indexingStart.placeholder")
                : format.dateTime(new Date(indexing_start), {
                    dateStyle: "medium",
                  })}
            </Text>
          </InputHorizontal>
        </Section>
      </Card>
    </Collapsible>
  );
}
