"use client";

import Button from "@/refresh-components/buttons/Button";
import Calendar from "@/refresh-components/Calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { useState } from "react";
import { SvgCalendar } from "@opal/icons";

export interface InputDatePickerProps {
  selectedDate: Date | null;
  setSelectedDate: (date: Date | null) => void;
  startYear?: number;
  disabled?: boolean;
}

function extractYear(date: Date | null): number {
  return (date ?? new Date()).getFullYear();
}

export default function InputDatePicker({
  selectedDate,
  setSelectedDate,
  startYear = 1970,
  disabled = false,
}: InputDatePickerProps) {
  const validStartYear = Math.max(startYear, 1970);
  const currYear = extractYear(new Date());
  const years = Array(currYear - validStartYear + 1)
    .fill(currYear)
    .map((currYear, index) => currYear - index);
  const [open, setOpen] = useState(false);
  const [displayedMonth, setDisplayedMonth] = useState<Date>(
    selectedDate ?? new Date()
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button leftIcon={SvgCalendar} secondary disabled={disabled}>
          {selectedDate ? selectedDate.toLocaleDateString() : "Select Date"}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="flex w-full flex-col items-center p-2 gap-3 data-[state=open]:animate-fade-in-scale data-[state=closed]:animate-fade-out-scale">
        <div className="flex flex-row items-center justify-center gap-2 w-full">
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
                  {year}
                </InputSelect.Item>
              ))}
            </InputSelect.Content>
          </InputSelect>
          <Button
            onClick={() => {
              const now = new Date();
              setSelectedDate(now);
              setDisplayedMonth(now);
              setOpen(false);
            }}
          >
            Today
          </Button>
        </div>
        <Calendar
          mode="single"
          selected={selectedDate ?? undefined}
          onSelect={(date) => {
            if (date) {
              setSelectedDate(date);
              setOpen(false);
            }
          }}
          month={displayedMonth}
          onMonthChange={setDisplayedMonth}
          fromDate={new Date(validStartYear, 0)}
          toDate={new Date()}
          showOutsideDays={false}
        />
      </PopoverContent>
    </Popover>
  );
}
