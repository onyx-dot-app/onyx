import {
  DateRangePicker,
  DateRangePickerItem,
  DateRangePickerValue,
  Text,
} from "@tremor/react";
import { getXDaysAgo } from "./dateUtils";

export const THIRTY_DAYS = "30d";

export function DateRangeSelector({
  value,
  onValueChange,
}: {
  value: DateRangePickerValue;
  onValueChange: (value: DateRangePickerValue) => void;
}) {
  return (
    <div>
      <Text className="my-auto mr-2 font-medium mb-1">Date Range</Text>
      <DateRangePicker
        className="max-w-md"
        value={value}
        onValueChange={onValueChange}
        selectPlaceholder="Select"
        enableClear={false}
      >
        <DateRangePickerItem
          key={THIRTY_DAYS}
          value={THIRTY_DAYS}
          from={getXDaysAgo(30)}
          to={getXDaysAgo(0)}
        >
          Last 30 days
        </DateRangePickerItem>
        <DateRangePickerItem
          key="today"
          value="today"
          from={getXDaysAgo(1)}
          to={getXDaysAgo(0)}
        >
          Today
        </DateRangePickerItem>
      </DateRangePicker>
    </div>
  );
}
