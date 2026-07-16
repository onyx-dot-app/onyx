// Pure source contract + the internal_search_filters builder. Mirrors backend DocumentSource
// (snake_case wire values) and BaseFilters (backend/onyx/context/search/models.py) — at Tier-2 the
// only field the source sub-view sets is `source_type`. No React — jest-unit-testable.
import type { IconFunctionComponent } from "@/icons/types";
import SvgGlobe from "@/icons/globe";

// The snake_case wire value, e.g. "web", "google_drive", "confluence".
export type DocumentSource = string;

// Tier-2 subset of BaseFilters; all other fields default null on the backend, so we omit them.
export interface InternalSearchFilters {
  source_type: DocumentSource[] | null;
}

export interface SourceMeta {
  icon: IconFunctionComponent;
  displayName: string;
}

// "google_drive" → "Google Drive": the label for a source not found in SOURCE_META.
function humanizeSource(source: DocumentSource): string {
  return source
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

// Per-connector logos + labels; a source absent here falls back to a generic icon + humanized name.
export const SOURCE_META: Record<DocumentSource, SourceMeta> = {};

export function getSourceMeta(source: DocumentSource): SourceMeta {
  return (
    SOURCE_META[source] ?? {
      icon: SvgGlobe,
      displayName: humanizeSource(source),
    }
  );
}

// null when nothing is selected → the backend applies no source filter.
export function buildInternalSearchFilters(
  selectedSources: DocumentSource[],
): InternalSearchFilters | null {
  if (selectedSources.length === 0) return null;
  return { source_type: selectedSources };
}
