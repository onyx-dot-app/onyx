import type { TimelineTranslate } from "@/app/app/message/messageComponents/toolDisplayHelpers";
import { ResponseItem } from "@/app/app/services/streamingModels";
import { OnyxDocument } from "@/lib/search/types";
import { getSourceDisplayName, isValidSource } from "@/lib/sources";
import { ValidSources } from "@/lib/types";
import {
  firstTool,
  isComplete as itemsComplete,
  toolMetadata,
} from "@/app/app/services/responseItems";

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

export function constructCurrentSearchState(
  items: ResponseItem[]
): SearchState {
  const tool = firstTool(items);
  const result = toolMetadata(items, "search_result").at(-1);
  const argumentQueries = tool?.arguments.queries;
  const queries = result?.queries.length
    ? result.queries
    : Array.isArray(argumentQueries)
      ? argumentQueries.filter(
          (query): query is string => typeof query === "string"
        )
      : [];
  const results = result?.displayed_docs ?? result?.search_docs ?? [];
  return {
    queries: [...new Set(queries)],
    results,
    sourceFilters: result?.sources ?? [],
    timeFilter:
      result && (result.time_filter_start || result.time_filter_end)
        ? { start: result.time_filter_start, end: result.time_filter_end }
        : null,
    isSearching: !!tool && !itemsComplete(items),
    hasResults: results.length > 0,
    isComplete: itemsComplete(items),
    isInternetSearch: tool?.name === "web_search",
  };
}
