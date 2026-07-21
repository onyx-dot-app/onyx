import {
  PacketType,
  SearchToolPacket,
  SearchToolStart,
  SearchToolQueriesDelta,
  SearchToolFilterDelta,
  SearchToolDocumentsDelta,
  SectionEnd,
} from "@/app/app/services/streamingModels";
import { OnyxDocument } from "@/lib/search/interfaces";
import { getSourceDisplayName, isValidSource } from "@/lib/sources";
import { ValidSources } from "@/lib/types";

export const MAX_TITLE_LENGTH = 25;

export const getMetadataTags = (metadata?: {
  [key: string]: string;
}): string[] | undefined => {
  if (!metadata) return undefined;
  const tags = Object.values(metadata)
    .filter((value) => typeof value === "string" && value.length > 0)
    .slice(0, 2)
    .map((value) => `# ${value}`);
  return tags.length > 0 ? tags : undefined;
};

export const INITIAL_QUERIES_TO_SHOW = 3;
export const QUERIES_PER_EXPANSION = 5;
export const INITIAL_RESULTS_TO_SHOW = 3;
export const RESULTS_PER_EXPANSION = 10;

// Applied time window; null == no time filter, either bound may be open-ended.
export interface TimeFilter {
  start: string | null;
  end: string | null;
}

export interface SearchState {
  queries: string[];
  results: OnyxDocument[];
  sourceFilters: string[];
  timeFilter: TimeFilter | null;
  isSearching: boolean;
  hasResults: boolean;
  isComplete: boolean;
  isInternetSearch: boolean;
}

const MAX_HEADER_SOURCES = 3;

// The bounds are day-granularity UTC dates; format in UTC so a midnight start
// doesn't render as the previous day in western timezones. Locale is pinned to
// match the surrounding hardcoded-English header copy.
const formatFilterDate = (iso: string): string =>
  new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });

// Phrases a window as "since <date>", "before <date>", or "from <date> to <date>".
export const formatTimeWindow = (
  timeFilter: TimeFilter | null
): string | null => {
  if (!timeFilter) return null;
  const { start, end } = timeFilter;
  if (start && end) {
    return `from ${formatFilterDate(start)} to ${formatFilterDate(end)}`;
  }
  if (start) return `since ${formatFilterDate(start)}`;
  if (end) return `before ${formatFilterDate(end)}`;
  return null;
};

export const formatSearchHeader = (
  sourceFilters: string[],
  timeFilter: TimeFilter | null = null
): string => {
  let base: string;
  if (sourceFilters.length === 0) {
    base = "Searching internal documents";
  } else {
    const names = sourceFilters.map((source) =>
      isValidSource(source)
        ? getSourceDisplayName(source as ValidSources)
        : source
    );
    const shown = names.slice(0, MAX_HEADER_SOURCES);
    const overflow = names.length - shown.length;
    const label =
      overflow > 0 ? `${shown.join(", ")} +${overflow} more` : shown.join(", ");
    base = `Searching ${label}`;
  }
  const timeWindowText = formatTimeWindow(timeFilter);
  return timeWindowText ? `${base} (${timeWindowText})` : base;
};

/** Constructs the current search state from search tool packets. */
export const constructCurrentSearchState = (
  packets: SearchToolPacket[]
): SearchState => {
  const searchStart = packets.find(
    (packet) => packet.obj.type === PacketType.SEARCH_TOOL_START
  )?.obj as SearchToolStart | null;

  const queryDeltas = packets
    .filter(
      (packet) => packet.obj.type === PacketType.SEARCH_TOOL_QUERIES_DELTA
    )
    .map((packet) => packet.obj as SearchToolQueriesDelta);

  const filterDeltas = packets
    .filter((packet) => packet.obj.type === PacketType.SEARCH_TOOL_FILTER_DELTA)
    .map((packet) => packet.obj as SearchToolFilterDelta);

  // Time rides on the same filter delta; take the latest one carrying a bound.
  const timeDelta = filterDeltas
    .filter(
      (delta) =>
        delta.time_filter_start != null || delta.time_filter_end != null
    )
    .at(-1);
  const timeFilter: TimeFilter | null = timeDelta
    ? {
        start: timeDelta.time_filter_start ?? null,
        end: timeDelta.time_filter_end ?? null,
      }
    : null;

  const documentDeltas = packets
    .filter(
      (packet) => packet.obj.type === PacketType.SEARCH_TOOL_DOCUMENTS_DELTA
    )
    .map((packet) => packet.obj as SearchToolDocumentsDelta);

  const searchEnd = packets.find(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  )?.obj as SectionEnd | null;

  // Deduplicate queries using Set for O(n) instead of indexOf which is O(n²)
  const seenQueries = new Set<string>();
  const queries = queryDeltas
    .flatMap((delta) => delta?.queries || [])
    .filter((query) => {
      if (seenQueries.has(query)) return false;
      seenQueries.add(query);
      return true;
    });

  // Deduped union of every connector a filter was applied to this search block.
  const seenSources = new Set<string>();
  const sourceFilters = filterDeltas
    .flatMap((delta) => delta?.sources || [])
    .filter((source) => {
      if (seenSources.has(source)) return false;
      seenSources.add(source);
      return true;
    });

  const seenDocIds = new Set<string>();
  const results = documentDeltas
    .flatMap((delta) => delta?.documents || [])
    .filter((doc) => {
      if (!doc || !doc.document_id) return false;
      if (seenDocIds.has(doc.document_id)) return false;
      seenDocIds.add(doc.document_id);
      return true;
    });

  const isSearching = Boolean(searchStart && !searchEnd);
  const hasResults = results.length > 0;
  const isComplete = Boolean(searchStart && searchEnd);
  const isInternetSearch = searchStart?.is_internet_search || false;

  return {
    queries,
    results,
    sourceFilters,
    timeFilter,
    isSearching,
    hasResults,
    isComplete,
    isInternetSearch,
  };
};
