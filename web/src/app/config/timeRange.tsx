import { getXDaysAgo, getXYearsAgo } from "@/lib/dateUtils";

export const timeRangeValues = [
  { label: "Last 2 years", value: getXYearsAgo(2) },
  { label: "Last year", value: getXYearsAgo(1) },
  { label: "Last 30 days", value: getXDaysAgo(30) },
  { label: "Last 7 days", value: getXDaysAgo(7) },
  { label: "Today", value: getXDaysAgo(1) },
];
