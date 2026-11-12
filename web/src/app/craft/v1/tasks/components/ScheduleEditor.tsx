"use client";

import { useTranslations } from "next-intl";
import {
  Card,
  InputSingleSelect,
  InputTypeIn,
  SelectButton,
  Tabs,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgCalendar, SvgClock, SvgRefreshCw } from "@opal/icons";
import type {
  DailyWeeklyPayload,
  EditorMode,
  EditorPayload,
  IntervalPayload,
  IntervalUnit,
} from "@/app/craft/v1/tasks/types";

const WEEKDAY_LABELS = [
  { value: 0, key: "sun" },
  { value: 1, key: "mon" },
  { value: 2, key: "tue" },
  { value: 3, key: "wed" },
  { value: 4, key: "thu" },
  { value: 5, key: "fri" },
  { value: 6, key: "sat" },
] as const;

const INTERVAL_UNITS: ReadonlyArray<IntervalUnit> = ["minutes", "hours"];
const DEFAULT_INTERVAL: IntervalPayload = { unit: "hours", every: 1 };
const DEFAULT_DAILY_WEEKLY: DailyWeeklyPayload = {
  time_of_day: "09:00",
  weekdays: [1, 2, 3, 4, 5],
};

export interface ScheduleEditorProps {
  mode: EditorMode;
  onModeChange: (mode: EditorMode) => void;
  payload: EditorPayload;
  onPayloadChange: (payload: EditorPayload) => void;
  error?: string | null;
}

export default function ScheduleEditor({
  mode,
  onModeChange,
  payload,
  onPayloadChange,
  error,
}: ScheduleEditorProps) {
  const t = useTranslations("craft.tasks.scheduleEditor");
  return (
    <Section height="auto" alignItems="stretch" gap={3}>
      <Card padding={5} border="solid" rounding={4}>
        <Tabs
          value={mode}
          gap={6}
          onValueChange={(next) => {
            if (next !== "interval" && next !== "daily_weekly") return;
            onModeChange(next);
            if (next === "interval" && !("unit" in payload)) {
              onPayloadChange(DEFAULT_INTERVAL);
            } else if (next === "daily_weekly" && !("weekdays" in payload)) {
              onPayloadChange(DEFAULT_DAILY_WEEKLY);
            }
          }}
        >
          <Tabs.List>
            <Tabs.Trigger value="interval" icon={SvgRefreshCw}>
              {t("tabs.interval")}
            </Tabs.Trigger>
            <Tabs.Trigger value="daily_weekly" icon={SvgCalendar}>
              {t("tabs.dailyWeekly")}
            </Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value="interval">
            <IntervalEditor
              payload={"unit" in payload ? payload : DEFAULT_INTERVAL}
              onChange={onPayloadChange}
            />
          </Tabs.Content>
          <Tabs.Content value="daily_weekly">
            <DailyWeeklyEditor
              payload={"weekdays" in payload ? payload : DEFAULT_DAILY_WEEKLY}
              onChange={onPayloadChange}
            />
          </Tabs.Content>
        </Tabs>
      </Card>
      {error && (
        <Text font="main-ui-body" color="status-error-05">
          {error}
        </Text>
      )}
    </Section>
  );
}

interface IntervalEditorProps {
  payload: IntervalPayload;
  onChange: (payload: IntervalPayload) => void;
}

function IntervalEditor({ payload, onChange }: IntervalEditorProps) {
  const t = useTranslations("craft.tasks.scheduleEditor");
  const tInputSelect = useTranslations("common.inputSelect");
  return (
    <Section height="auto" alignItems="start" gap={3}>
      <Text font="secondary-action" color="text-03">
        {t("interval.everyLabel")}
      </Text>
      <Section
        height="auto"
        flexDirection="row"
        justifyContent="start"
        gap={3}
        wrap
      >
        <Section width={7} height="auto" gap={0}>
          <InputTypeIn
            type="number"
            min={1}
            aria-label={t("interval.everyLabel")}
            value={String(payload.every ?? 1)}
            onChange={(e) =>
              onChange({ ...payload, every: Number(e.target.value) || 1 })
            }
            data-testid="interval-every"
          />
        </Section>
        <Section width={9} height="auto" gap={0}>
          <InputSingleSelect
            value={payload.unit}
            onValueChange={(unit) => {
              if (unit === "minutes" || unit === "hours")
                onChange({ ...payload, unit });
            }}
            defaultOption={INTERVAL_UNITS[0]}
            placeholder={tInputSelect("placeholder.fallback")}
            options={INTERVAL_UNITS.map((unit) => ({
              value: unit,
              title: t(`intervalUnits.${unit}`),
            }))}
          />
        </Section>
      </Section>
    </Section>
  );
}

interface DailyWeeklyEditorProps {
  payload: DailyWeeklyPayload;
  onChange: (payload: DailyWeeklyPayload) => void;
}

function DailyWeeklyEditor({ payload, onChange }: DailyWeeklyEditorProps) {
  const t = useTranslations("craft.tasks.scheduleEditor");
  const weekdaySet = new Set(payload.weekdays ?? []);
  const selectedDays = WEEKDAY_LABELS.filter((day) =>
    weekdaySet.has(day.value)
  ).map((day) => t(`weekdays.${day.key}`));
  const scheduleNote =
    selectedDays.length === 0 || selectedDays.length === 7
      ? t("dailyWeekly.runsEveryDay")
      : t("dailyWeekly.runsOn", { days: selectedDays.join(", ") });
  return (
    <Section height="auto" alignItems="stretch" gap={5}>
      <Section height="auto" alignItems="start" gap={3}>
        <Text font="secondary-action" color="text-03">
          {t("dailyWeekly.daysLabel")}
        </Text>
        <Section
          height="auto"
          flexDirection="row"
          justifyContent="start"
          gap={2}
          wrap
          role="group"
          aria-label={t("dailyWeekly.daysLabel")}
        >
          {WEEKDAY_LABELS.map((day) => {
            const selected = weekdaySet.has(day.value);
            return (
              <SelectButton
                key={day.value}
                size="md"
                state={selected ? "selected" : "empty"}
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
              >
                {t(`weekdays.${day.key}`)}
              </SelectButton>
            );
          })}
        </Section>
      </Section>
      <Section height="auto" alignItems="start" gap={3}>
        <Text font="secondary-action" color="text-03">
          {t("dailyWeekly.atLabel")}
        </Text>
        <Section width={11} height="auto" gap={0}>
          <InputTypeIn
            type="time"
            aria-label={t("dailyWeekly.atLabel")}
            value={payload.time_of_day ?? "09:00"}
            onChange={(e) =>
              onChange({ ...payload, time_of_day: e.target.value })
            }
            data-testid="daily-weekly-time"
          />
        </Section>
        <Text font="secondary-body" color="text-03">
          {t("localTimeHint")}
        </Text>
      </Section>
      <Card padding={3} color="background-tint-01">
        <Section
          height="auto"
          flexDirection="row"
          justifyContent="start"
          gap={2}
        >
          <SvgClock size={16} className="text-text-03" />
          <Text font="secondary-body" color="text-03">
            {scheduleNote}
          </Text>
        </Section>
      </Card>
    </Section>
  );
}
