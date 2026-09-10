import type { Tag } from "@/lib/types";
import type { SourceMetadata } from "@/lib/search/interfaces";
import type { DateRangePickerValue } from "@opal/components";
import type { SearchFiltersRequest } from "@/lib/searchFilters/types";

/** Freezes a live selection into the shape the backend receives.
 *
 * `allSources` is everything the selection was made from. A selection covering
 * all of it is the default, not a filter, and goes as no source filter at all —
 * sending the full list instead makes the backend report an applied filter and
 * the UI name every connector it searched.
 */
export function buildFilters(
  sources: SourceMetadata[],
  allSources: SourceMetadata[],
  documentSets: string[],
  timeRange: DateRangePickerValue | null,
  tags: Tag[]
): SearchFiltersRequest {
  const selected = new Set(sources.map((source) => source.internalName));
  const coversAllSources =
    allSources.length > 0 &&
    allSources.every((source) => selected.has(source.internalName));

  return {
    source_type:
      sources.length > 0 && !coversAllSources
        ? sources.map((source) => source.internalName)
        : null,
    document_set: documentSets.length > 0 ? documentSets : null,
    updated_at_range: timeRange?.from
      ? { start: timeRange.from, end: null }
      : null,
    tags: tags,
  };
}
