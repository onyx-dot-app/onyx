"use client";

import "@opal/components/inputs/shared.css";
import React from "react";
import type { InputVariants } from "@opal/types";
import { Button, Calendar, Popover, Text } from "@opal/components";
import { SvgCalendar, SvgX } from "@opal/icons";
import {
  SEGMENT_INPUT_PROPS,
  SegmentSeparator,
  cleanPastedText,
  makeSegmentKeyDownHandler,
  toAsciiDigits,
  usePendingCaret,
} from "@opal/components/inputs/segmented";
import { useOpalStrings } from "@opal/strings";

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
  { part: "month", placeholder: "MM", maxLen: 2 },
  { part: "day", placeholder: "DD", maxLen: 2 },
  { part: "year", placeholder: "YYYY", maxLen: 4 },
] as const;

type SegmentField = (typeof SEGMENT_FIELDS)[number];

// The keys that separate date parts, typed or pasted: 10/19/2026,
// 10-19-2026, 10.19.2026.
const DATE_SEPARATOR = /[/.-]/;

// Pads a one-digit month or day ("1" → "01"); other lengths stay as is.
function padPart(digits: string, maxLen: number): string {
  return digits.length === 1 ? digits.padStart(maxLen, "0") : digits;
}

// Reads pasted text as a whole date: MM/DD/YYYY, or YYYY-MM-DD when the first
// part has four digits. Returns null for anything else.
function parsePastedDate(pieces: string[]): Segments | null {
  if (pieces.length !== 3) return null;
  const [first = "", second = "", third = ""] = pieces;
  const [month, day, year] =
    first.length === 4 ? [second, third, first] : [first, second, third];
  if (
    month === "" ||
    month.length > 2 ||
    day === "" ||
    day.length > 2 ||
    year.length !== 4
  ) {
    return null;
  }
  return { month: padPart(month, 2), day: padPart(day, 2), year };
}

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

  /**
   * Text shown in place of the empty segments while the field is empty and
   * unfocused (e.g. "All time"). Focus reveals the segments.
   */
  placeholder?: string;
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
  placeholder,
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
  const [focused, setFocused] = React.useState(false);
  const strings = useOpalStrings();

  const monthRef = React.useRef<HTMLInputElement>(null);
  const dayRef = React.useRef<HTMLInputElement>(null);
  const yearRef = React.useRef<HTMLInputElement>(null);
  const segmentRefs = { month: monthRef, day: dayRef, year: yearRef };
  const popoverContentRef = React.useRef<HTMLDivElement>(null);
  const pendingCaretRef = usePendingCaret(segments);

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

  const handleSegmentKeyDown = makeSegmentKeyDownHandler(segments, commit);

  // Typing: digits fill the segment and a full segment moves focus on. Typing
  // past a full segment is blocked. A separator key in the month or day
  // splits the segment at the caret: digits before it stay (padded, "1" →
  // "01"), digits after it move to the front of the next segment, and focus
  // moves there. Any other non-digit does nothing.
  function handleSegmentChange(
    field: SegmentField,
    next: SegmentField | undefined
  ) {
    return (e: React.ChangeEvent<HTMLInputElement>) => {
      const raw = toAsciiDigits(e.target.value);
      const separatorAt = raw.search(DATE_SEPARATOR);
      if (separatorAt < 0 || !next) {
        const digits = raw.replace(/\D/g, "");
        if (digits.length > field.maxLen) return;
        setSegments({ ...segments, [field.part]: digits });
        if (next && digits.length === field.maxLen) {
          segmentRefs[next.part].current?.focus();
        }
        return;
      }

      const before = raw.slice(0, separatorAt).replace(/\D/g, "");
      const moved = raw.slice(separatorAt + 1).replace(/\D/g, "");
      setSegments({
        ...segments,
        [field.part]: padPart(before, field.maxLen),
        [next.part]: (moved + segments[next.part]).slice(0, next.maxLen),
      });
      const nextInput = segmentRefs[next.part].current;
      if (!nextInput) return;
      nextInput.focus();
      if (moved) {
        // Caret just after the separator, ahead of the moved digits.
        pendingCaretRef.current = { input: nextInput, position: 0 };
      } else {
        nextInput.select();
      }
    };
  }

  // Pasting reads the text as a date, whichever segment has focus. Only
  // whitespace and direction marks are dropped; the rest must be digits:
  // - a whole date (10/19/2026, 10-19-2026, 2026-10-19) fills every segment;
  // - digits alone go into the focused segment at the caret, clipped to fit;
  // - anything else ("10/19", "Oct 19", "1/2/26"): not a date, so ignored.
  function handlePaste(field: SegmentField) {
    return (e: React.ClipboardEvent<HTMLInputElement>) => {
      e.preventDefault();
      const pieces = cleanPastedText(e.clipboardData.getData("text")).split(
        DATE_SEPARATOR
      );
      if (pieces.some((piece) => /\D/.test(piece))) return;

      const [digits = ""] = pieces;
      if (pieces.length !== 1) {
        const date = parsePastedDate(pieces);
        if (date) setSegments(date);
        return;
      }
      if (digits === "") return;

      const input = e.currentTarget;
      const start = input.selectionStart ?? input.value.length;
      const end = input.selectionEnd ?? start;
      const inserted = (
        input.value.slice(0, start) +
        digits +
        input.value.slice(end)
      ).slice(0, field.maxLen);
      setSegments({ ...segments, [field.part]: inserted });
      const caret = Math.min(start + digits.length, inserted.length);
      pendingCaretRef.current = { input, position: caret };
    };
  }

  // Commit when focus leaves the whole field. The calendar content is
  // portaled, so containment is checked against it too or opening the
  // popover would commit (or revert) a half-typed draft.
  function handleRootBlur(e: React.FocusEvent<HTMLDivElement>) {
    const next = e.relatedTarget as Node | null;
    if (e.currentTarget.contains(next)) return;
    if (next && popoverContentRef.current?.contains(next)) return;
    setFocused(false);
    commit(segments);
  }

  function handleCalendarSelect(date: Date | undefined) {
    if (!date) return;
    onChange(date);
    setOpen(false);
  }

  const separator = <SegmentSeparator>/</SegmentSeparator>;
  const showPlaceholder =
    !!placeholder &&
    value == null &&
    !focused &&
    !open &&
    !segments.month &&
    !segments.day &&
    !segments.year;

  return (
    <div className="opal-input-segmented-root">
      <Popover open={open} onOpenChange={setOpen}>
        <div
          className="opal-input opal-input-segmented"
          data-variant={variant}
          onFocus={() => setFocused(true)}
          onBlur={handleRootBlur}
        >
          <div
            className="opal-input-segmented-content"
            role="group"
            aria-label={strings.date}
            data-placeholder-shown={showPlaceholder || undefined}
          >
            {/* The segments stay mounted under the placeholder, so a click or
                Tab still lands in the month segment and reveals them. */}
            {showPlaceholder && (
              <span className="opal-input-segmented-placeholder">
                <Text
                  font="main-ui-body"
                  color={disabled ? "text-01" : "text-02"}
                >
                  {placeholder}
                </Text>
              </span>
            )}
            {SEGMENT_FIELDS.map((field, i) => (
              <React.Fragment key={field.part}>
                {i > 0 && separator}
                {/* raw-ok: segmented numeric fields have no Opal input primitive. The field chrome is the surrounding .opal-input. */}
                <input
                  {...SEGMENT_INPUT_PROPS}
                  disabled={disabled}
                  ref={segmentRefs[field.part]}
                  id={field.part === "month" ? id : undefined}
                  aria-label={strings[field.part]}
                  placeholder={field.placeholder}
                  data-wide={field.part === "year" ? true : undefined}
                  value={segments[field.part]}
                  onChange={handleSegmentChange(field, SEGMENT_FIELDS[i + 1])}
                  onPaste={handlePaste(field)}
                  onKeyDown={handleSegmentKeyDown(
                    field.part,
                    i > 0 ? segmentRefs[SEGMENT_FIELDS[i - 1]!.part] : null,
                    i < SEGMENT_FIELDS.length - 1
                      ? segmentRefs[SEGMENT_FIELDS[i + 1]!.part]
                      : null
                  )}
                />
              </React.Fragment>
            ))}
          </div>

          <div
            role="presentation"
            className="opal-input-segmented-actions"
            // Escape on an action returns focus to the field's first segment.
            onKeyDown={(event) => {
              if (event.key === "Escape") monthRef.current?.focus();
            }}
          >
            <Popover.Trigger asChild>
              <Button
                icon={SvgCalendar}
                prominence="tertiary"
                size="sm"
                tooltip={strings.openCalendar}
                aria-label={strings.openCalendar}
                disabled={disabled}
              />
            </Popover.Trigger>
            {/* The clear action is always the field's last control. */}
            {clearable && value && !disabled && (
              <Button
                icon={SvgX}
                prominence="tertiary"
                size="sm"
                tooltip={strings.clear}
                aria-label={strings.clear}
                onClick={() => onChange(null)}
              />
            )}
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
