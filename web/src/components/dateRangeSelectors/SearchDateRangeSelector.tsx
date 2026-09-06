import { DateRangePickerValue } from "@/refresh-components/DateRangePicker";
import { useTranslations } from "next-intl";
import { FiCalendar, FiChevronDown, FiXCircle } from "react-icons/fi";
import { CustomDropdown } from "../Dropdown";
import { timeRangeValues } from "@/app/config/timeRange";
import { TimeRangeSelector } from "@/components/filters/TimeRangeSelector";
import { cn } from "@opal/utils";

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
  const t = useTranslations("common.dateRange");
  return (
    <div>
      <CustomDropdown
        dropdown={
          <TimeRangeSelector
            value={value}
            className={cn(
              "border border-border bg-background rounded-lg flex flex-col w-64 max-h-96 overflow-y-auto overscroll-contain",
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
          <FiCalendar className="flex-none my-auto me-2" />{" "}
          <p className="line-clamp-1">
            {isHorizontal ? (
              t("date.label")
            ) : value?.selectValue ? (
              <div className="text-text-darker">{value.selectValue}</div>
            ) : (
              t("anyTime.text")
            )}
          </p>
          {value?.selectValue ? (
            <button
              type="button"
              aria-label={t("clearButton.ariaLabel")}
              className="my-auto ms-auto p-0.5 rounded-full w-fit"
              onClick={(e) => {
                onValueChange(null);
                e.stopPropagation();
              }}
            >
              <FiXCircle />
            </button>
          ) : (
            <FiChevronDown className="my-auto ms-auto" />
          )}
        </div>
      </CustomDropdown>
    </div>
  );
}
