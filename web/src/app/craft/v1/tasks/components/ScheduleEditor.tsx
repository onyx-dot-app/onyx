"use client";

import { useMemo } from "react";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import SimpleTabs from "@/refresh-components/SimpleTabs";
import { Section } from "@/layouts/general-layouts";
import { cn } from "@opal/utils";
import type {
  AdvancedPayload,
  DailyWeeklyPayload,
  EditorMode,
  EditorPayload,
  IntervalPayload,
  IntervalUnit,
} from "@/app/craft/v1/tasks/interfaces";
import { compileToCron } from "@/app/craft/v1/tasks/schedule";

// 0=Sun..6=Sat (cron convention).
const WEEKDAY_LABELS: ReadonlyArray<{ value: number; short: string }> = [
  { value: 0, short: "Sun" },
  { value: 1, short: "Mon" },
  { value: 2, short: "Tue" },
  { value: 3, short: "Wed" },
  { value: 4, short: "Thu" },
  { value: 5, short: "Fri" },
  { value: 6, short: "Sat" },
];

const INTERVAL_UNITS: ReadonlyArray<{ value: IntervalUnit; label: string }> = [
  { value: "minutes", label: "minutes" },
  { value: "hours", label: "hours" },
  { value: "days", label: "days" },
];

export interface ScheduleEditorProps {
  mode: EditorMode;
  onModeChange: (mode: EditorMode) => void;
  payload: EditorPayload;
  onPayloadChange: (payload: EditorPayload) => void;
  /** Error message to display below the editor. */
  error?: string | null;
}

export default function ScheduleEditor({
  mode,
  onModeChange,
  payload,
  onPayloadChange,
  error,
}: ScheduleEditorProps) {
  // Cache the active payload per mode so flipping tabs back and forth doesn't
  // wipe out a partially-filled form on the other tab.
  const tabContent = useMemo(
    () => ({
      interval: {
        name: "Interval",
        content: (
          <IntervalEditor
            payload={
              mode === "interval"
                ? (payload as IntervalPayload)
                : DEFAULT_INTERVAL
            }
            onChange={onPayloadChange}
          />
        ),
      },
      daily_weekly: {
        name: "Daily / Weekly",
        content: (
          <DailyWeeklyEditor
            payload={
              mode === "daily_weekly"
                ? (payload as DailyWeeklyPayload)
                : DEFAULT_DAILY_WEEKLY
            }
            onChange={onPayloadChange}
          />
        ),
      },
      advanced: {
        name: "Advanced",
        content: (
          <AdvancedEditor
            payload={
              mode === "advanced"
                ? (payload as AdvancedPayload)
                : DEFAULT_ADVANCED
            }
            onChange={onPayloadChange}
          />
        ),
      },
    }),
    [mode, payload, onPayloadChange]
  );

  const compiled = compileToCron(mode, payload);

  return (
    <Section gap={0.5}>
      <SimpleTabs
        tabs={tabContent}
        value={mode}
        onValueChange={(value) => {
          const next = value as EditorMode;
          onModeChange(next);
          // Reset to defaults if switching modes (only when current payload
          // doesn't match the target mode shape).
          if (next === "interval" && !isIntervalPayload(payload)) {
            onPayloadChange(DEFAULT_INTERVAL);
          } else if (
            next === "daily_weekly" &&
            !isDailyWeeklyPayload(payload)
          ) {
            onPayloadChange(DEFAULT_DAILY_WEEKLY);
          } else if (next === "advanced" && !isAdvancedPayload(payload)) {
            onPayloadChange(DEFAULT_ADVANCED);
          }
        }}
      />
      {error ? (
        <Text mainUiBody text03 className="text-status-error-05">
          {error}
        </Text>
      ) : compiled.ok ? (
        <Text secondaryBody text03>
          Cron: <code className="font-mono">{compiled.cron}</code>
        </Text>
      ) : null}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Defaults / type-guards
// ---------------------------------------------------------------------------

const DEFAULT_INTERVAL: IntervalPayload = { unit: "hours", every: 1 };
const DEFAULT_DAILY_WEEKLY: DailyWeeklyPayload = {
  time_of_day: "09:00",
  weekdays: [1, 2, 3, 4, 5],
};
const DEFAULT_ADVANCED: AdvancedPayload = { cron: "0 9 * * 1" };

function isIntervalPayload(p: EditorPayload): p is IntervalPayload {
  return (
    typeof (p as IntervalPayload).unit === "string" &&
    typeof (p as IntervalPayload).every !== "undefined"
  );
}

function isDailyWeeklyPayload(p: EditorPayload): p is DailyWeeklyPayload {
  return Array.isArray((p as DailyWeeklyPayload).weekdays);
}

function isAdvancedPayload(p: EditorPayload): p is AdvancedPayload {
  return typeof (p as AdvancedPayload).cron === "string";
}

// ---------------------------------------------------------------------------
// Interval
// ---------------------------------------------------------------------------

interface IntervalEditorProps {
  payload: IntervalPayload;
  onChange: (payload: IntervalPayload) => void;
}

function IntervalEditor({ payload, onChange }: IntervalEditorProps) {
  const showTimeOfDay = payload.unit === "days";
  return (
    <Section gap={0.5}>
      <div className="flex items-center gap-2 flex-wrap">
        <Text mainUiBody text05>
          Every
        </Text>
        <div className="w-20">
          <InputTypeIn
            type="number"
            min={1}
            value={String(payload.every ?? 1)}
            onChange={(e) =>
              onChange({ ...payload, every: Number(e.target.value) || 1 })
            }
            data-testid="interval-every"
          />
        </div>
        <div className="w-32">
          <InputSelect
            value={payload.unit}
            onValueChange={(value) =>
              onChange({ ...payload, unit: value as IntervalUnit })
            }
          >
            <InputSelect.Trigger />
            <InputSelect.Content>
              {INTERVAL_UNITS.map((u) => (
                <InputSelect.Item key={u.value} value={u.value}>
                  {u.label}
                </InputSelect.Item>
              ))}
            </InputSelect.Content>
          </InputSelect>
        </div>
      </div>
      {showTimeOfDay && (
        <div className="flex items-center gap-2">
          <Text mainUiBody text05>
            At
          </Text>
          <div className="w-32">
            <InputTypeIn
              type="time"
              value={payload.time_of_day ?? "09:00"}
              onChange={(e) =>
                onChange({ ...payload, time_of_day: e.target.value })
              }
              data-testid="interval-time"
            />
          </div>
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Daily / Weekly
// ---------------------------------------------------------------------------

interface DailyWeeklyEditorProps {
  payload: DailyWeeklyPayload;
  onChange: (payload: DailyWeeklyPayload) => void;
}

function DailyWeeklyEditor({ payload, onChange }: DailyWeeklyEditorProps) {
  const weekdaySet = new Set(payload.weekdays ?? []);
  return (
    <Section gap={0.5}>
      <div className="flex items-center gap-2">
        <Text mainUiBody text05>
          At
        </Text>
        <div className="w-32">
          <InputTypeIn
            type="time"
            value={payload.time_of_day ?? "09:00"}
            onChange={(e) =>
              onChange({ ...payload, time_of_day: e.target.value })
            }
            data-testid="daily-weekly-time"
          />
        </div>
      </div>
      <div className="flex flex-col gap-1">
        <Text secondaryBody text03>
          On these days (leave all unchecked for every day):
        </Text>
        <div className="flex items-center gap-1 flex-wrap">
          {WEEKDAY_LABELS.map((day) => {
            const selected = weekdaySet.has(day.value);
            return (
              <button
                type="button"
                key={day.value}
                onClick={() => {
                  const next = new Set(weekdaySet);
                  if (selected) next.delete(day.value);
                  else next.add(day.value);
                  onChange({
                    ...payload,
                    weekdays: Array.from(next).sort((a, b) => a - b),
                  });
                }}
                data-testid={`weekday-${day.value}`}
                aria-pressed={selected}
                className={cn(
                  "px-3 py-1 rounded-08 border text-sm transition-colors",
                  selected
                    ? "bg-action-link-01 border-action-link-03 text-text-05"
                    : "bg-background-neutral-00 border-border-02 text-text-03 hover:bg-background-tint-01"
                )}
              >
                {day.short}
              </button>
            );
          })}
        </div>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Advanced (raw cron)
// ---------------------------------------------------------------------------

interface AdvancedEditorProps {
  payload: AdvancedPayload;
  onChange: (payload: AdvancedPayload) => void;
}

function AdvancedEditor({ payload, onChange }: AdvancedEditorProps) {
  return (
    <Section gap={0.5}>
      <Text secondaryBody text03>
        Five-field cron expression (minute hour day-of-month month day-of-week).
      </Text>
      <InputTypeIn
        value={payload.cron ?? ""}
        onChange={(e) => onChange({ cron: e.target.value })}
        placeholder="0 9 * * 1"
        data-testid="advanced-cron"
      />
    </Section>
  );
}
