import { DateRange } from "../../../../../components/dateRangeSelectors/AdminDateRangeSelector";
import { START_QUERY_HISTORY_EXPORT_URL } from "./constants";

export const withRequestId = (url: string, requestId: string): string =>
  `${url}?request_id=${requestId}`;

export const withDateRange = (dateRange: DateRange): string => {
  if (!dateRange) {
    return START_QUERY_HISTORY_EXPORT_URL;
  }

  const { from, to } = dateRange;

  const fromString = from.toISOString();
  const toString = to.toISOString();

  return `${START_QUERY_HISTORY_EXPORT_URL}?start=${fromString}&end=${toString}`;
};
