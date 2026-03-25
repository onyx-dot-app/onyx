"use client";

import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { toast } from "@/hooks/useToast";
import Calendar from "@/refresh-components/Calendar";
import Popover from "@/refresh-components/Popover";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { useState } from "react";
import { SvgCalendar } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";

export interface InputDatePickerProps {
  name?: string;
  selectedDate: Date | null;
  setSelectedDate: (date: Date | null) => void;
  startYear?: number;
  disabled?: boolean;
  maxDate?: Date;
  maxDateErrorMessage?: string;
}

function extractYear(date: Date | null): number {
  return (date ?? new Date()).getFullYear();
}

function normalizeDate(date: Date): Date {
  const normalizedDate = new Date(date);
  normalizedDate.setHours(0, 0, 0, 0);
  return normalizedDate;
}

function isAfterDate(date: Date, maxDate: Date): boolean {
  return normalizeDate(date).getTime() > normalizeDate(maxDate).getTime();
}

function clampToMaxDate(date: Date, maxDate?: Date): Date {
  if (!maxDate || !isAfterDate(date, maxDate)) {
    return date;
  }

  return normalizeDate(maxDate);
}

export default function InputDatePicker({
  name,
  selectedDate,
  setSelectedDate,
  startYear = 1970,
  disabled = false,
  maxDate,
  maxDateErrorMessage = "Please choose today or an earlier date.",
}: InputDatePickerProps) {
  const validStartYear = Math.max(startYear, 1970);
  const normalizedMaxDate = maxDate ? normalizeDate(maxDate) : undefined;
  const currYear = extractYear(normalizedMaxDate ?? new Date());
  const years = Array(currYear - validStartYear + 1)
    .fill(currYear)
    .map((currYear, index) => currYear - index);
  const [open, setOpen] = useState(false);
  const [displayedMonth, setDisplayedMonth] = useState<Date>(
    clampToMaxDate(
      selectedDate ?? normalizedMaxDate ?? new Date(),
      normalizedMaxDate
    )
  );

  function notifyInvalidDateSelection() {
    toast.warning(maxDateErrorMessage);
  }

  function handleDateSelection(date: Date) {
    if (normalizedMaxDate && isAfterDate(date, normalizedMaxDate)) {
      notifyInvalidDateSelection();
      return;
    }

    setSelectedDate(date);
    setDisplayedMonth(date);
    setOpen(false);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild id={name} name={name}>
        <Disabled disabled={disabled}>
          <Button prominence="secondary" icon={SvgCalendar}>
            {selectedDate ? selectedDate.toLocaleDateString() : "Select Date"}
          </Button>
        </Disabled>
      </Popover.Trigger>
      <Popover.Content>
        <Section padding={0.25}>
          <Section flexDirection="row" gap={0.5}>
            <InputSelect
              value={`${extractYear(displayedMonth)}`}
              onValueChange={(value) => {
                const year = parseInt(value);
                setDisplayedMonth(new Date(year, 0));
              }}
            >
              <InputSelect.Trigger />
              <InputSelect.Content>
                {years.map((year) => (
                  <InputSelect.Item key={year} value={`${year}`}>
                    {`${year}`}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelect>
            <Button
              onClick={() => {
                const now = normalizedMaxDate ?? new Date();
                setSelectedDate(now);
                setDisplayedMonth(now);
                setOpen(false);
              }}
            >
              Today
            </Button>
          </Section>
          <Calendar
            mode="single"
            selected={selectedDate ?? undefined}
            onSelect={(date) => {
              if (date) {
                handleDateSelection(date);
              }
            }}
            onDayClick={(date) => {
              if (normalizedMaxDate && isAfterDate(date, normalizedMaxDate)) {
                notifyInvalidDateSelection();
              }
            }}
            month={displayedMonth}
            onMonthChange={setDisplayedMonth}
            disabled={
              normalizedMaxDate ? [{ after: normalizedMaxDate }] : undefined
            }
            startMonth={new Date(validStartYear, 0)}
            endMonth={normalizedMaxDate ?? new Date()}
            showOutsideDays={false}
          />
        </Section>
      </Popover.Content>
    </Popover>
  );
}
