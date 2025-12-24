import Button from "@/refresh-components/buttons/Button";
import { Calendar } from "@/components/ui/calendar";
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
  onClear?: () => void;
}

function extractYear(date: Date | null): number {
  return (date ?? new Date()).getFullYear();
}

export default function InputDatePicker({
  selectedDate,
  setSelectedDate,
  startYear = 1970,
  disabled = false,
  onClear,
}: InputDatePickerProps) {
  const validStartYear = Math.max(startYear, 1970);
  const currYear = extractYear(new Date());
  const years = Array(currYear - validStartYear + 1)
    .fill(currYear)
    .map((currYear, index) => currYear - index);
  const [shownDate, setShownDate] = useState(selectedDate ?? new Date());
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button leftIcon={SvgCalendar} secondary disabled={disabled}>
          {selectedDate ? selectedDate.toLocaleDateString() : "Select Date"}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="flex w-full flex-col items-center p-4 gap-y-3 data-[state=open]:animate-fade-in-scale data-[state=closed]:animate-fade-out-scale">
        <div className="flex flex-row items-center justify-center gap-x-2 w-full">
          <InputSelect
            value={`${extractYear(shownDate)}`}
            onValueChange={(value) => {
              setShownDate(new Date(parseInt(value), 0));
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
              setShownDate(now);
              setSelectedDate(now);
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
              setShownDate(date);
              setSelectedDate(date);
              setOpen(false);
            }
          }}
          defaultMonth={shownDate}
          startMonth={new Date(validStartYear, 0)}
          endMonth={new Date()}
          className="rounded-md"
        />
        <Button
          secondary
          onClick={() => {
            setSelectedDate(null);
            onClear?.();
          }}
          className="w-full"
        >
          Clear
        </Button>
      </PopoverContent>
    </Popover>
  );
}
