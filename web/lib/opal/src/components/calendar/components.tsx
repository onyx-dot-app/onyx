"use client";

import "@opal/components/calendar/styles.css";
import React from "react";
import { DayPicker } from "react-day-picker";
import { Button } from "@opal/components";
import { SvgChevronLeft, SvgChevronRight } from "@opal/icons";

// Omit must distribute over DayPicker's per-mode props union, or the
// mode/selected/onSelect discrimination collapses.
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown
  ? Omit<T, K>
  : never;

type CalendarProps = DistributiveOmit<
  React.ComponentProps<typeof DayPicker>,
  | "className"
  | "style"
  | "classNames"
  | "styles"
  | "components"
  | "formatters"
  | "modifiersClassNames"
  | "modifiersStyles"
  | "showOutsideDays"
>;

type NavButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement>;

function PreviousMonthButton({
  className: _className,
  children: _children,
  ...props
}: NavButtonProps) {
  return (
    <Button icon={SvgChevronLeft} prominence="internal" size="sm" {...props} />
  );
}

function NextMonthButton({
  className: _className,
  children: _children,
  ...props
}: NavButtonProps) {
  return (
    <Button icon={SvgChevronRight} prominence="internal" size="sm" {...props} />
  );
}

/**
 * Calendar (Figma Date Picker): month grid on react-day-picker.
 * Supports the DayPicker selection modes (single/multiple/range). Opal owns
 * all chrome, so the styling escape hatches are stripped from the props.
 */
function Calendar(props: CalendarProps) {
  return (
    <DayPicker
      // Spread first so the Opal-owned chrome below wins even against
      // untyped callers that smuggle in stripped props. Every key in the
      // CalendarProps omit list is re-pinned here so none survive the spread.
      {...props}
      className={undefined}
      style={undefined}
      styles={undefined}
      formatters={undefined}
      modifiersClassNames={undefined}
      modifiersStyles={undefined}
      // Outside days render as empty fixed-width cells, never as numerals.
      showOutsideDays={false}
      classNames={{
        root: "opal-calendar",
        months: "opal-calendar-months",
        month: "opal-calendar-month",
        nav: "opal-calendar-nav",
        month_caption: "opal-calendar-caption",
        caption_label: "opal-calendar-caption-label",
        month_grid: "opal-calendar-grid",
        weekdays: "opal-calendar-weekdays",
        weekday: "opal-calendar-weekday",
        weeks: "opal-calendar-weeks",
        week: "opal-calendar-week",
        day: "opal-calendar-cell",
        day_button: "opal-calendar-day",
        today: "opal-calendar-cell--today",
        disabled: "opal-calendar-cell--disabled",
        focused: "opal-calendar-cell--focused",
        selected: "opal-calendar-cell--selected",
        range_start: "opal-calendar-cell--range-start",
        range_middle: "opal-calendar-cell--range-middle",
        range_end: "opal-calendar-cell--range-end",
      }}
      components={{ PreviousMonthButton, NextMonthButton }}
    />
  );
}

export { Calendar, type CalendarProps };
