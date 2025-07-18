import { FiCalendar } from "react-icons/fi";
import { Button } from "./button";
import Text from "./text";
import { Calendar } from "./calendar";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./select";
import { useState } from "react";

export interface DatePickerProps {
  selectedDate: Date | null;
  setSelectedDate: (date: Date | null) => void;
  startYear?: number;
  disabled?: boolean;
  onClear?: () => void;
}

function extractYear(date: Date | null): number {
  return (date ?? new Date()).getFullYear();
}

export function DatePicker({
  selectedDate,
  setSelectedDate,
  startYear = 1970,
  disabled = false,
  onClear,
}: DatePickerProps) {
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
        <Button
          icon={FiCalendar}
          variant="outline"
          className="px-6 w-[150px] disabled:cursor-not-allowed"
          disabled={disabled}
        >
          {selectedDate ? selectedDate.toLocaleDateString() : "Select Date"}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="flex w-full flex-col p-2 gap-y-2 data-[state=open]:animate-fade-in-scale data-[state=closed]:animate-fade-out-scale">
        <div className="flex flex-row items-center gap-x-2">
          <Select
            onValueChange={(value) => {
              setShownDate(new Date(parseInt(value), 0));
            }}
            defaultValue={`${extractYear(shownDate)}`}
          >
            <SelectTrigger>
              <SelectValue>{extractYear(shownDate)}</SelectValue>
            </SelectTrigger>
            <SelectContent position="popper">
              {years.map((year) => (
                <SelectItem key={year} value={`${year}`}>
                  {year}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
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
          className="px-0"
          selected={selectedDate ?? undefined}
          onDayClick={(date) => {
            setShownDate(date);
            setSelectedDate(date);
            setOpen(false);
          }}
          month={shownDate}
          onMonthChange={(date) => {
            setShownDate(date);
          }}
          toMonth={new Date()}
          fromMonth={new Date(validStartYear, 0)}
        />
        <Button
          variant="outline"
          onClick={() => {
            setSelectedDate(null);
            onClear?.();
          }}
        >
          <Text className="text-red-600">Clear</Text>
        </Button>
      </PopoverContent>
    </Popover>
  );
}
