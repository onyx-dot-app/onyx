"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { Tag } from "@/lib/types";
import type { SourceMetadata } from "@/lib/search/interfaces";
import type { InputDateRangePickerValue } from "@opal/components";
import type { SearchFilters } from "@/lib/searchFilters/types";

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
