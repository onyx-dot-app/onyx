import { memo, useState } from "react";
import { endOfDay, format, isSameDay, startOfDay, subDays } from "date-fns";
import { Calendar } from "@opal/components/calendar/components";
import { Popover } from "@opal/components/popover/components";
import { SelectButton } from "@opal/components/buttons/select-button/components";
import { SvgCalendar } from "@opal/icons";
import { useOpalStrings, type OpalStrings } from "@opal/strings";

export const THIRTY_DAYS = "1M";

export type InputDateRangePickerValue = DateRange & {
  selectValue: string;
};

export type DateRange =
  | {
      from: Date;
      to: Date;
    }
  | undefined;

type DraftDateRange =
  | {
      from: Date;
      to?: Date;
    }
  | undefined;

interface DatePreset {
  label: string;
  inclusiveDays: number;
}

const PRESETS: DatePreset[] = [
  { label: "1D", inclusiveDays: 1 },
  { label: "7D", inclusiveDays: 7 },
  { label: "1M", inclusiveDays: 30 },
  { label: "3M", inclusiveDays: 90 },
];

export function rangeForInclusiveDays(
  inclusiveDays: number,
  now = new Date()
): Exclude<DateRange, undefined> {
  const utcToday = new Date(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate()
  );
  const to = endOfDay(utcToday);
  return { from: startOfDay(subDays(to, inclusiveDays - 1)), to };
}

function rangeForPreset(preset: DatePreset): Exclude<DateRange, undefined> {
  return rangeForInclusiveDays(preset.inclusiveDays);
}

function rangesMatch(left: DateRange, right: DateRange): boolean {
  return Boolean(
    left?.from &&
    left.to &&
    right?.from &&
    right.to &&
    isSameDay(left.from, right.from) &&
    isSameDay(left.to, right.to)
  );
}

type SelectorSize = "md" | "sm";

// Display labels are looked up per preset so the stable `label` ids used for
// range matching stay untranslated.
function presetDisplayLabel(strings: OpalStrings, preset: DatePreset): string {
  switch (preset.inclusiveDays) {
    case 1:
      return strings.dateRangeOneDay;
    case 7:
      return strings.dateRangeSevenDays;
    case 30:
      return strings.dateRangeOneMonth;
    case 90:
      return strings.dateRangeThreeMonths;
    default:
      return preset.label;
  }
}

export const InputDateRangePicker = memo(function InputDateRangePicker({
  value,
  onValueChange,
  size = "md",
}: {
  value: DateRange;
  onValueChange: (value: DateRange) => void;
  size?: SelectorSize;
}) {
  const strings = useOpalStrings();
  const buttonSize = size === "sm" ? "sm" : "md";
  const [isOpen, setIsOpen] = useState(false);
  const [draftRange, setDraftRange] = useState<DraftDateRange>(value);
  const [pendingStart, setPendingStart] = useState<Date>();
  const [hoveredEnd, setHoveredEnd] = useState<Date>();

  const activePreset = PRESETS.find((preset) =>
    rangesMatch(value, rangeForPreset(preset))
  );
  const customActive = !activePreset;
  const hasCustomRange = customActive && !!value;
  const customLabel =
    customActive && value
      ? `${format(value.from, value.from.getFullYear() === value.to.getFullYear() ? "MMM d" : "MMM d, y")} – ${format(value.to, value.from.getFullYear() === value.to.getFullYear() ? "MMM d" : "MMM d, y")}`
      : strings.dateRangeCustom;

  function selectPreset(preset: DatePreset) {
    const range = rangeForPreset(preset);
    setDraftRange(range);
    setPendingStart(undefined);
    setHoveredEnd(undefined);
    setIsOpen(false);
    onValueChange(range);
  }

  return (
    <div
      className="inline-flex max-w-full shrink-0 items-center overflow-x-auto rounded-12 border border-border-02 bg-background-tint-03 p-0.5"
      role="group"
      aria-label={strings.dateRange}
      data-testid="admin-date-range-selector"
    >
      {PRESETS.map((preset) => {
        const active = !isOpen && activePreset?.label === preset.label;

        return (
          <SelectButton
            key={preset.label}
            size={buttonSize}
            state={active ? "selected" : "empty"}
            aria-pressed={active}
            onClick={() => selectPreset(preset)}
          >
            {presetDisplayLabel(strings, preset)}
          </SelectButton>
        );
      })}

      <Popover
        open={isOpen}
        onOpenChange={(open) => {
          setIsOpen(open);
          setPendingStart(undefined);
          setHoveredEnd(undefined);
          setDraftRange(open && customActive ? value : undefined);
        }}
      >
        <Popover.Trigger asChild>
          <SelectButton
            size={buttonSize}
            state={customActive || isOpen ? "selected" : "empty"}
            rightIcon={hasCustomRange ? undefined : SvgCalendar}
            aria-label={
              value
                ? strings.dateRangeCustomRange(
                    format(value.from, "MMM d, y"),
                    format(value.to, "MMM d, y")
                  )
                : strings.dateRangeChooseCustom
            }
            aria-pressed={customActive}
            aria-haspopup="dialog"
            aria-expanded={isOpen}
            data-testid="admin-date-range-selector-button"
          >
            {customLabel}
          </SelectButton>
        </Popover.Trigger>

        <Popover.Content align="end">
          <div className="flex w-full justify-center">
            <Calendar
              mode="range"
              defaultMonth={customActive ? value?.from : undefined}
              selected={draftRange}
              modifiers={
                pendingStart && hoveredEnd
                  ? {
                      range_preview_start:
                        pendingStart < hoveredEnd ? pendingStart : hoveredEnd,
                      range_preview_middle: {
                        after:
                          pendingStart < hoveredEnd ? pendingStart : hoveredEnd,
                        before:
                          pendingStart < hoveredEnd ? hoveredEnd : pendingStart,
                      },
                      range_preview_end:
                        pendingStart < hoveredEnd ? hoveredEnd : pendingStart,
                    }
                  : undefined
              }
              onDayMouseEnter={(day) => {
                if (pendingStart) setHoveredEnd(day);
              }}
              onDayClick={(day) => {
                if (!pendingStart) {
                  setDraftRange({ from: day });
                  setPendingStart(day);
                  setHoveredEnd(undefined);
                  return;
                }

                const from = startOfDay(
                  day < pendingStart ? day : pendingStart
                );
                const to = endOfDay(day < pendingStart ? pendingStart : day);

                setPendingStart(undefined);
                setHoveredEnd(undefined);
                setDraftRange({ from, to });
                onValueChange({ from, to });
                setIsOpen(false);
              }}
              numberOfMonths={1}
              disabled={(date) => date > new Date()}
            />
          </div>
        </Popover.Content>
      </Popover>
    </div>
  );
});
