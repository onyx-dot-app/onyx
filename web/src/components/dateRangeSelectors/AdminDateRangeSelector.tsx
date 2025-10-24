import React, { memo, useState } from "react";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import Button from "@/refresh-components/buttons/Button";
import { cn } from "@/lib/utils";
import { format } from "date-fns";
import { getXDaysAgo } from "./dateUtils";
import SvgCalendar from "@/icons/calendar";

export const THIRTY_DAYS = "30d";

export type DateRangePickerValue = DateRange & {
  selectValue: string;
};

export type DateRange =
  | {
      from: Date;
      to: Date;
    }
  | undefined;

export const AdminDateRangeSelector = memo(function AdminDateRangeSelector({
  value,
  onValueChange,
}: {
  value: DateRange;
  onValueChange: (value: DateRange) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);

  const presets = [
    {
      label: "Last 30 days",
      value: {
        from: getXDaysAgo(30),
        to: getXDaysAgo(0),
      },
    },
    {
      label: "Today",
      value: {
        from: getXDaysAgo(1),
        to: getXDaysAgo(0),
      },
    },
  ];

  return (
    <div className="grid gap-2">
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <PopoverTrigger asChild>
          <Button
            secondary
            className={cn("justify-start", !value && "text-muted-foreground")}
            leftIcon={SvgCalendar}
          >
            {value?.from
              ? value.to
                ? `${format(value.from, "LLL dd, y")} - ${format(
                    value.to,
                    "LLL dd, y"
                  )}`
                : format(value.from, "LLL dd, y")
              : "Pick a date range"}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            initialFocus
            mode="range"
            defaultMonth={value?.from}
            selected={value}
            onSelect={(range) => {
              if (range?.from) {
                if (range.to) {
                  // Normal range selection when initialized with a range
                  onValueChange({ from: range.from, to: range.to });
                } else {
                  // Single date selection when initilized without a range
                  const to = new Date(range.from);
                  const from = new Date(to.setDate(to.getDate() - 1));
                  onValueChange({ from, to });
                }
              }
            }}
            numberOfMonths={2}
          />
          <div className="border-t p-3">
            {presets.map((preset) => (
              <Button
                key={preset.label}
                internal
                className="w-full justify-start"
                onClick={() => {
                  onValueChange(preset.value);
                }}
              >
                {preset.label}
              </Button>
            ))}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
});
