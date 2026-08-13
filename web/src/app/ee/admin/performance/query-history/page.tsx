"use client";

import { SettingsLayouts } from "@opal/layouts";
import {
  QueryHistoryFilters,
  QueryHistoryTable,
} from "@/app/ee/admin/performance/query-history/QueryHistoryTable";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  DateRange,
  DateRangePicker,
  rangeForInclusiveDays,
} from "@/refresh-components/DateRangePicker";
import { useCallback, useState } from "react";

const route = ADMIN_ROUTES.QUERY_HISTORY;

export default function QueryHistoryPage() {
  const initialRange = rangeForInclusiveDays(30);
  const [dateRange, setDateRange] = useState<DateRange>(initialRange);
  const [filters, setFilters] = useState<QueryHistoryFilters>(() => {
    return {
      start_time: initialRange.from.toISOString(),
      end_time: initialRange.to.toISOString(),
    };
  });

  const onTimeRangeChange = useCallback((value: DateRange) => {
    setDateRange(value);

    if (value?.from && value?.to) {
      setFilters((previous) => ({
        ...previous,
        start_time: value.from.toISOString(),
        end_time: value.to.toISOString(),
      }));
      return;
    }

    setFilters((previous) => {
      const nextFilters = { ...previous };
      delete nextFilters.start_time;
      delete nextFilters.end_time;
      return nextFilters;
    });
  }, []);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        divider
        rightChildren={
          <DateRangePicker
            value={dateRange}
            onValueChange={onTimeRangeChange}
          />
        }
      />

      <SettingsLayouts.Body>
        <QueryHistoryTable
          dateRange={dateRange}
          filters={filters}
          setFilters={setFilters}
        />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
