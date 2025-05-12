import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { FiCalendar, FiChevronDown, FiXCircle } from "react-icons/fi";
import { CustomDropdown } from "../Dropdown";
import { timeRangeValues } from "@/app/config/timeRange";
import { TimeRangeSelector } from "@/components/filters/TimeRangeSelector";
import { cn } from "@/lib/utils";

export function SearchDateRangeSelector({
  value,
  onValueChange,
  isHorizontal,
  className,
}: {
  value: DateRangePickerValue | null;
  onValueChange: (value: DateRangePickerValue | null) => void;
  isHorizontal?: boolean;
  className?: string;
}) {
  return (
    <div>
      <CustomDropdown
        dropdown={
          <TimeRangeSelector
            value={value}
            className={cn(
              "border border-border bg-background rounded-lg flex flex-col w-64 max-h-96 overflow-y-auto flex overscroll-contain",
              className
            )}
            timeRangeValues={timeRangeValues}
            onValueChange={onValueChange}
          />
        }
      >
        <div
          className={`
            flex 
            text-sm  
            px-3
            line-clamp-1
            py-1.5 
            rounded-lg 
            border 
            border-border 
            cursor-pointer 
            hover:bg-accent-background-hovered`}
        >
          <FiCalendar className="flex-none my-auto mr-2" />{" "}
          <p className="line-clamp-1">
            {isHorizontal ? (
              "Date"
            ) : value?.selectValue ? (
              <div className="text-text-darker">{value.selectValue}</div>
            ) : (
              "Any time..."
            )}
          </p>
          {value?.selectValue ? (
            <div
              className="my-auto ml-auto p-0.5 rounded-full w-fit"
              onClick={(e) => {
                onValueChange(null);
                e.stopPropagation();
              }}
            >
              <FiXCircle />
            </div>
          ) : (
            <FiChevronDown className="my-auto ml-auto" />
          )}
        </div>
      </CustomDropdown>
    </div>
  );
}
