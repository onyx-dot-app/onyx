import type { TimelineTranslate } from "@/app/app/message/messageComponents/toolDisplayHelpers";
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

// The bounds are day-granularity UTC dates. Format in UTC so a midnight start
// doesn't render as the previous day in western timezones.
const formatFilterDate = (iso: string, locale: string): string =>
  new Date(iso).toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });

// Phrases a window with the timeWindow catalog entries: since, before, or between.
export const formatTimeWindow = (
  timeFilter: TimeFilter | null,
  t: TimelineTranslate,
  locale: string
): string | null => {
  if (!timeFilter) return null;
  const { start, end } = timeFilter;
  if (start && end) {
    return t("internalSearch.timeWindow.between", {
      start: formatFilterDate(start, locale),
      end: formatFilterDate(end, locale),
    });
  }
  if (start) {
    return t("internalSearch.timeWindow.since", {
      date: formatFilterDate(start, locale),
    });
  }
  if (end) {
    return t("internalSearch.timeWindow.before", {
      date: formatFilterDate(end, locale),
    });
  }
  return null;
};

export const formatSearchHeader = (
  sourceFilters: string[],
  timeFilter: TimeFilter | null,
  t: TimelineTranslate,
  locale: string
): string => {
  let header: string;
  if (sourceFilters.length === 0) {
    header = t("internalSearch.header.default");
  } else {
    const names = sourceFilters.map((source) =>
      isValidSource(source)
        ? getSourceDisplayName(source as ValidSources)
        : source
    );
    const shown = names.slice(0, MAX_HEADER_SOURCES).join(", ");
    const overflow = names.length - MAX_HEADER_SOURCES;
    const sources =
      overflow > 0
        ? t("internalSearch.header.sourcesOverflow", {
            sources: shown,
            count: overflow,
          })
        : shown;
    header = t("internalSearch.header.sources", { sources });
  }
  const timeWindow = formatTimeWindow(timeFilter, t, locale);
  return timeWindow
    ? t("internalSearch.header.withTimeWindow", { header, timeWindow })
    : header;
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
