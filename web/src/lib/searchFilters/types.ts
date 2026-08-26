import type { Tag } from "@/lib/types";
import type { SourceMetadata } from "@/lib/search/interfaces";
import type { DateRangePickerValue } from "@/refresh-components/DateRangePicker";

/** The live selection a user edits: which sources, sets, tags and dates to search. */
export interface SearchFilters {
  timeRange: DateRangePickerValue | null;
  setTimeRange: React.Dispatch<
    React.SetStateAction<DateRangePickerValue | null>
  >;
  selectedSources: SourceMetadata[];
  setSelectedSources: React.Dispatch<React.SetStateAction<SourceMetadata[]>>;
  selectedDocumentSets: string[];
  setSelectedDocumentSets: React.Dispatch<React.SetStateAction<string[]>>;
  selectedTags: Tag[];
  setSelectedTags: React.Dispatch<React.SetStateAction<Tag[]>>;
  getFilterString: () => string;
  buildFiltersFromQueryString: (
    filterString: string,
    availableSources: SourceMetadata[],
    availableDocumentSets: string[],
    availableTags: Tag[]
  ) => void;
  clearFilters: () => void;
}

export interface TimeRange {
  start: Date | string | null;
  end: Date | string | null;
}

/**
 * The frozen form of a {@link SearchFilters}, as the backend receives it.
 *
 * Built by `buildFilters` at send time: rich objects become identifiers,
 * empty selections become null, and the setters and methods fall away.
 */
export interface SearchFiltersRequest {
  source_type: string[] | null;
  document_set: string[] | null;
  updated_at_range: TimeRange | null;
  // `buildFilters` has always sent this and the backend has always read it
  // (BaseFilters.tags in onyx/context/search/models.py). It went undeclared
  // because the old body returned via a variable, which skips the excess
  // property check a returned literal gets.
  tags: Tag[];
}
