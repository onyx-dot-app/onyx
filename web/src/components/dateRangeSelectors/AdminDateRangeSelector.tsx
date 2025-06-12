import React, { memo, useState } from "react";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CalendarIcon } from "lucide-react";
import { format } from "date-fns";
import { getXDaysAgo } from "./dateUtils";

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
            variant="outline"
            className={cn(
              "w-[300px] justify-start text-left font-normal",
              !value && "text-muted-foreground"
            )}
          >
            <CalendarIcon className="mr-2 h-4 w-4" />
            {value?.from ? (
              value.to ? (
                <>
                  {format(value.from, "LLL dd, y")} -{" "}
                  {format(value.to, "LLL dd, y")}
                </>
              ) : (
                format(value.from, "LLL dd, y")
              )
            ) : (
              <span>Pick a date range</span>
            )}
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
                variant="ghost"
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
