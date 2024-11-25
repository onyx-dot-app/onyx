import { Tag } from "../types";
import { Filters, SourceMetadata } from "./interfaces";
import { DateRangePickerValue } from "@/app/ee/admin/performance/DateRangeSelector";

export const buildFilters = (
  sources: SourceMetadata[],
  documentSets: string[],
  timeRange: DateRangePickerValue | null,
  tags: Tag[]
): Filters => {
  const filters = {
    source_type:
      sources.length > 0 ? sources.map((source) => source.internalName) : null,
    document_set: documentSets.length > 0 ? documentSets : null,
    time_cutoff: timeRange?.from ? timeRange.from : null,
    tags: tags,
  };

  return filters;
};

export function endsWithLetterOrNumber(str: string) {
  return /[a-zA-Z0-9]$/.test(str);
}
