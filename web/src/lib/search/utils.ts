import { Tag, ValidSources } from "../types";
import { Filters, OnyxDocument, SourceMetadata } from "./interfaces";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";

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

// If we have a link, open it in a new tab (including if it's a file)
// If above fails and we have a file, update the presenting document
export const openDocument = (
  document: OnyxDocument,
  updatePresentingDocument?: (document: OnyxDocument) => void
) => {
  if (document.link) {
    window.open(document.link, "_blank");
  } else if (document.source_type === ValidSources.File) {
    updatePresentingDocument?.(document);
  }
};
