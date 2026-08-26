import type { Tag } from "@/lib/types";
import type { SourceMetadata } from "@/lib/search/interfaces";
import type { DateRangePickerValue } from "@/refresh-components/DateRangePicker";
import type { Filters } from "@/lib/searchFilters/types";

/** Freezes a live selection into the shape the backend receives. */
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
    updated_at_range: timeRange?.from
      ? { start: timeRange.from, end: null }
      : null,
    tags: tags,
  };

  return filters;
};
