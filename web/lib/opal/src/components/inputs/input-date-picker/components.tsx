"use client";

import "@opal/components/inputs/shared.css";
import React from "react";
import type { InputVariants } from "@opal/types";
import { Button, Calendar, Popover } from "@opal/components";
import { SvgCalendar, SvgX } from "@opal/icons";
import {
  SEGMENT_INPUT_PROPS,
  SegmentSeparator,
  makeSegmentChangeHandler,
  makeSegmentKeyDownHandler,
} from "@opal/components/inputs/segmented";

// ---------------------------------------------------------------------------
// Segment helpers
// ---------------------------------------------------------------------------

interface Segments {
  month: string;
  day: string;
  year: string;
}

const EMPTY_SEGMENTS: Segments = { month: "", day: "", year: "" };

const SEGMENT_FIELDS = [
  { part: "month", label: "Month", placeholder: "MM", maxLen: 2 },
  { part: "day", label: "Day", placeholder: "DD", maxLen: 2 },
  { part: "year", label: "Year", placeholder: "YYYY", maxLen: 4 },
] as const;

function toSegments(date: Date | null): Segments {
  if (!date) return EMPTY_SEGMENTS;
  return {
    month: String(date.getMonth() + 1).padStart(2, "0"),
    day: String(date.getDate()).padStart(2, "0"),
    year: String(date.getFullYear()).padStart(4, "0"),
  };
}

// Round-trip through Date to reject overflows like 02/31 (which Date would
// silently roll into March).
function parseSegments({ month, day, year }: Segments): Date | null {
  if (!month || !day || !year) return null;
  const m = Number(month);
  const d = Number(day);
  const y = Number(year);
  const date = new Date(y, m - 1, d);
  const valid =
    date.getFullYear() === y &&
    date.getMonth() === m - 1 &&
    date.getDate() === d;
  return valid ? date : null;
}

function startOfDay(date: Date): Date {
  const normalized = new Date(date);
  normalized.setHours(0, 0, 0, 0);
  return normalized;
}

// ---------------------------------------------------------------------------
// InputDatePicker
// ---------------------------------------------------------------------------

interface InputDatePickerProps {
  /** Selected date, or null when empty. */
  value: Date | null;

  /** Fires with the committed date, or null when cleared. */
  onChange: (date: Date | null) => void;

  /** Error chrome. */
  error?: boolean;
  disabled?: boolean;

  /** Shows a clear action while a value is set and the field is enabled. */
  clearable?: boolean;

  /** Earliest selectable day (inclusive). */
  minDate?: Date;

  /** Latest selectable day (inclusive). */
  maxDate?: Date;

  /** Applied to the month segment so a `<label htmlFor>` can target the field. */
  id?: string;
}

/**
 * InputDatePicker (Figma Input/Date): segmented MM/DD/YYYY field with a
 * calendar action that opens the Opal Calendar in a popover. Typing commits
 * on blur or Enter once the segments form a real in-range date. Picking in
 * the calendar commits immediately.
 */
function InputDatePicker({
  value,
  onChange,
  error,
  disabled,
  clearable,
  minDate,
  maxDate,
  id,
}: InputDatePickerProps) {
  const variant: InputVariants = disabled
    ? "disabled"
    : error
      ? "error"
      : "primary";

  const normalizedMin = minDate ? startOfDay(minDate) : undefined;
  const normalizedMax = maxDate ? startOfDay(maxDate) : undefined;

  const [segments, setSegments] = React.useState<Segments>(() =>
    toSegments(value)
  );
  const [open, setOpen] = React.useState(false);

  const monthRef = React.useRef<HTMLInputElement>(null);
  const dayRef = React.useRef<HTMLInputElement>(null);
  const yearRef = React.useRef<HTMLInputElement>(null);
  const segmentRefs = { month: monthRef, day: dayRef, year: yearRef };
  const popoverContentRef = React.useRef<HTMLDivElement>(null);

  const valueTime = value ? value.getTime() : null;
  React.useEffect(() => {
    setSegments(toSegments(value));
    // Key on the instant, not Date identity, so parent re-renders that
    // recreate an equal Date don't clobber in-progress typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valueTime]);

  function inRange(date: Date): boolean {
    const t = startOfDay(date).getTime();
    if (normalizedMin && t < normalizedMin.getTime()) return false;
    if (normalizedMax && t > normalizedMax.getTime()) return false;
    return true;
  }

  function commit(next: Segments) {
    const parsed = parseSegments(next);
    if (parsed && inRange(parsed)) {
      // Day-granularity compare: a value carrying a time-of-day must not
      // fire a midnight-normalizing onChange on an editless tab-through.
      const sameDay =
        value != null && parsed.getTime() === startOfDay(value).getTime();
      if (!sameDay) onChange(parsed);
      else setSegments(toSegments(value));
    } else {
      setSegments(toSegments(value));
    }
  }

  const handleSegmentChange = makeSegmentChangeHandler(setSegments);
  const handleSegmentKeyDown = makeSegmentKeyDownHandler(segments, commit);

  // Commit when focus leaves the whole field. The calendar content is
  // portaled, so containment is checked against it too or opening the
  // popover would commit (or revert) a half-typed draft.
  function handleRootBlur(e: React.FocusEvent<HTMLDivElement>) {
    const next = e.relatedTarget as Node | null;
    if (e.currentTarget.contains(next)) return;
    if (next && popoverContentRef.current?.contains(next)) return;
    commit(segments);
  }

  function handleCalendarSelect(date: Date | undefined) {
    if (!date) return;
    onChange(date);
    setOpen(false);
  }

  const separator = <SegmentSeparator>/</SegmentSeparator>;

  return (
    <div className="opal-input-segmented-root">
      <Popover open={open} onOpenChange={setOpen}>
        <div
          className="opal-input opal-input-segmented"
          data-variant={variant}
          role="group"
          aria-label="Date"
          onBlur={handleRootBlur}
        >
          <div className="opal-input-segmented-content">
            {SEGMENT_FIELDS.map((field, i) => (
              <React.Fragment key={field.part}>
                {i > 0 && separator}
                {/* raw-ok: segmented numeric fields have no Opal input primitive. The field chrome is the surrounding .opal-input. */}
                <input
                  {...SEGMENT_INPUT_PROPS}
                  disabled={disabled}
                  ref={segmentRefs[field.part]}
                  id={field.part === "month" ? id : undefined}
                  aria-label={field.label}
                  placeholder={field.placeholder}
                  maxLength={field.maxLen}
                  data-wide={field.part === "year" ? true : undefined}
                  value={segments[field.part]}
                  onChange={handleSegmentChange(
                    field.part,
                    field.maxLen,
                    i < SEGMENT_FIELDS.length - 1
                      ? segmentRefs[SEGMENT_FIELDS[i + 1]!.part]
                      : null
                  )}
                  onKeyDown={handleSegmentKeyDown(
                    field.part,
                    i > 0 ? segmentRefs[SEGMENT_FIELDS[i - 1]!.part] : null
                  )}
                />
              </React.Fragment>
            ))}
          </div>

          <div className="opal-input-segmented-actions">
            {clearable && value && !disabled && (
              <Button
                icon={SvgX}
                prominence="internal"
                size="sm"
                tooltip="Clear"
                onClick={() => onChange(null)}
              />
            )}
            <Popover.Trigger asChild>
              <Button
                icon={SvgCalendar}
                prominence="internal"
                size="sm"
                tooltip="Open calendar"
                disabled={disabled}
              />
            </Popover.Trigger>
          </div>
        </div>

        <Popover.Content ref={popoverContentRef} align="end">
          <Calendar
            mode="single"
            selected={value ?? undefined}
            onSelect={handleCalendarSelect}
            defaultMonth={value ?? normalizedMax ?? normalizedMin ?? undefined}
            startMonth={normalizedMin}
            endMonth={normalizedMax}
            disabled={
              normalizedMin || normalizedMax
                ? [
                    ...(normalizedMin ? [{ before: normalizedMin }] : []),
                    ...(normalizedMax ? [{ after: normalizedMax }] : []),
                  ]
                : undefined
            }
          />
        </Popover.Content>
      </Popover>
    </div>
  );
}

export { InputDatePicker, type InputDatePickerProps };
