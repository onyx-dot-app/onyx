"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { type SourceMetadata } from "@/lib/connectors/types/source";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { Tag } from "@/lib/types";
import type { InputDateRangePickerValue } from "@opal/components";
import type {
  SearchFilters,
  SearchFiltersRequest,
} from "@/lib/searchFilters/types";
import type { MinimalAgent } from "@/lib/agents/types";
import type { ChatSearchFilters } from "@/lib/tools/types";
import { useAvailableSources } from "@/lib/connectors/hooks";
import { getConfiguredSources } from "@/lib/connectors/utils";
import {
  agentDeclaresOwnSources,
  buildFilters,
  effectiveAvailableSourcesFor,
  selectedSourcesFrom,
} from "@/lib/searchFilters/utils";

/**
 * The search filters a chat sends, built from its stored selection against
 * the sources the agent can reach. A send and a saved tool selection both
 * read this, so a turn the server starts searches the same scope.
 *
 * An explicit source selection resolves only against a complete roster:
 * `settled` allows stale data (a failed revalidation must not drop a
 * restriction) but never a partial first load, which would narrow the
 * search wrongly. Until then no source filter is sent. An agent declaring its
 * own knowledge_sources carries its complete roster and never waits.
 */
export function useChatSearchFiltersRequest(
  agent: MinimalAgent | undefined,
  filters: ChatSearchFilters
): SearchFiltersRequest {
  const { availableSources, settled } = useAvailableSources();
  return useMemo(() => {
    const sources =
      agent && (settled || agentDeclaresOwnSources(agent))
        ? selectedSourcesFrom(
            filters,
            getConfiguredSources(
              effectiveAvailableSourcesFor(agent, availableSources)
            )
          )
        : null;
    return buildFilters(
      sources,
      filters.documentSets,
      filters.timeRange ? { from: filters.timeRange.from } : null,
      filters.tags
    );
  }, [agent, settled, availableSources, filters]);
}

export function useSearchFilters(): SearchFilters {
  const [timeRange, setTimeRange] = useState<InputDateRangePickerValue | null>(
    null
  );
  const [selectedSources, setSelectedSources] = useState<SourceMetadata[]>([]);
  const [selectedDocumentSets, setSelectedDocumentSets] = useState<string[]>(
    []
  );
  const [selectedTags, setSelectedTags] = useState<Tag[]>([]);

  const clearFilters = useCallback(function () {
    setTimeRange(null);
    setSelectedSources([]);
    setSelectedDocumentSets([]);
    setSelectedTags([]);
  }, []);

  // Memoized so the identity changes only when a filter does. Consumers read
  // this through a context, where a fresh object every render would re-render
  // all of them for nothing.
  return useMemo(
    () => ({
      clearFilters,
      timeRange,
      setTimeRange,
      selectedSources,
      setSelectedSources,
      selectedDocumentSets,
      setSelectedDocumentSets,
      selectedTags,
      setSelectedTags,
    }),
    [
      clearFilters,
      timeRange,
      selectedSources,
      selectedDocumentSets,
      selectedTags,
    ]
  );
}

interface TagsResponse {
  tags: Tag[];
}

/**
 * Fetches the set of valid tags from the server.
 *
 * Tags are deduplicated for 60 s and not re-fetched on window focus.
 *
 * @returns tags - The array of available {@link Tag} objects (empty while loading).
 * @returns isLoading - `true` until the first successful fetch or an error.
 * @returns error - The error object if the request failed.
 * @returns refresh - SWR mutate function to manually re-fetch.
 */
export function useTags() {
  const { data, error, mutate } = useSWR<TagsResponse>(
    SWR_KEYS.tags,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
  );

  return {
    tags: data?.tags ?? [],
    isLoading: !error && !data,
    error,
    refresh: mutate,
  };
}
