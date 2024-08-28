import { getXDaysAgo, getXYearsAgo } from "@/lib/dateUtils";
import { DateRangePickerValue } from "@tremor/react";
import { FiCalendar, FiChevronDown, FiXCircle } from "react-icons/fi";
import { CustomDropdown, DefaultDropdownElement } from "../Dropdown";


export const LAST_2_YEARS = "Last 2 years";
export const LAST_YEAR = "Last year";
export const LAST_30_DAYS = "Last 30 days";
export const LAST_7_DAYS = "Last 7 days";
export const TODAY = "Today";

export function DateRangeSelector({
  value,
  onValueChange,
  isHorizontal,
}: {
  value: DateRangePickerValue | null;
  onValueChange: (value: DateRangePickerValue | null) => void;
  isHorizontal?: boolean;
}) {
  return (
    <div>
      <CustomDropdown
        dropdown={
          <div
            className={`
              border 
              border-border 
              bg-background
              rounded-lg 
              flex 
              flex-col 
              w-64 
              max-h-96 
              overflow-y-auto 
              flex
              overscroll-contain`}
          >
            <DefaultDropdownElement
              key={LAST_2_YEARS}
              name={LAST_2_YEARS}
              onSelect={() =>
                onValueChange({
                  to: new Date(),
                  from: getXYearsAgo(2),
                  selectValue: LAST_2_YEARS,
                })
              }
              isSelected={value?.selectValue === LAST_2_YEARS}
            />

            <DefaultDropdownElement
              key={LAST_YEAR}
              name={LAST_YEAR}
              onSelect={() =>
                onValueChange({
                  to: new Date(),
                  from: getXYearsAgo(1),
                  selectValue: LAST_YEAR,
                })
              }
              isSelected={value?.selectValue === LAST_YEAR}
            />

            <DefaultDropdownElement
              key={LAST_30_DAYS}
              name={LAST_30_DAYS}
              onSelect={() =>
                onValueChange({
                  to: new Date(),
                  from: getXDaysAgo(30),
                  selectValue: LAST_30_DAYS,
                })
              }
              isSelected={value?.selectValue === LAST_30_DAYS}
            />

            <DefaultDropdownElement
              key={LAST_7_DAYS}
              name={LAST_7_DAYS}
              onSelect={() =>
                onValueChange({
                  to: new Date(),
                  from: getXDaysAgo(7),
                  selectValue: LAST_7_DAYS,
                })
              }
              isSelected={value?.selectValue === LAST_7_DAYS}
            />

            <DefaultDropdownElement
              key={TODAY}
              name={TODAY}
              onSelect={() =>
                onValueChange({
                  to: new Date(),
                  from: getXDaysAgo(1),
                  selectValue: TODAY,
                })
              }
              isSelected={value?.selectValue === TODAY}
            />
          </div>
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
            hover:bg-hover`}
        >
          <FiCalendar className="flex-none my-auto mr-2" />{" "}
          <p className="line-clamp-1">
            {isHorizontal ? (
              "Date"
            ) : value?.selectValue ? (
              <div className="text-emphasis">{value.selectValue}</div>
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
