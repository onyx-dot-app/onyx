"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { Tag, ValidSources } from "@/lib/types";
import type { SourceMetadata } from "@/lib/search/interfaces";
import type { DateRangePickerValue } from "@/refresh-components/DateRangePicker";
import { getConfiguredSources } from "@/lib/sources";
import type { SearchFilters } from "@/lib/searchFilters/types";

export function useSearchFilters(): SearchFilters {
  const [timeRange, setTimeRange] = useState<DateRangePickerValue | null>(null);
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

interface UseSourcePreferencesProps {
  availableSources: ValidSources[];
  selectedSources: SourceMetadata[];
  setSelectedSources: (sources: SourceMetadata[]) => void;
}

interface SourcePreferencesSnapshot {
  sourcePreferences: Record<string, boolean>; // uniqueKey -> enabled status
}

const LS_SELECTED_INTERNAL_SEARCH_SOURCES_KEY = "selectedInternalSearchSources";

export function useSourcePreferences({
  availableSources,
  selectedSources,
  setSelectedSources,
}: UseSourcePreferencesProps) {
  const [sourcesInitialized, setSourcesInitialized] = useState(false);

  const configuredSources = useMemo(
    () => getConfiguredSources(availableSources),
    [availableSources]
  );

  // Load saved source preferences from localStorage
  const loadSavedSourcePreferences = (): SourcePreferencesSnapshot | null => {
    if (typeof window === "undefined") return null;
    const saved = localStorage.getItem(LS_SELECTED_INTERNAL_SEARCH_SOURCES_KEY);
    if (!saved) return null;
    try {
      const res = JSON.parse(saved);

      // Validate the snapshot structure
      if (
        typeof res !== "object" ||
        res === null ||
        typeof res.sourcePreferences !== "object" ||
        res.sourcePreferences === null ||
        Array.isArray(res.sourcePreferences)
      ) {
        return null;
      }

      // Validate that all values in sourcePreferences are booleans
      for (const value of Object.values(res.sourcePreferences)) {
        if (typeof value !== "boolean") {
          return null;
        }
      }

      return res as SourcePreferencesSnapshot;
    } catch {
      return null;
    }
  };

  const persistSourcePreferencesState = (
    enabledSources: SourceMetadata[],
    allKnownSources: SourceMetadata[]
  ) => {
    if (typeof window === "undefined") return;

    const enabledKeys = new Set(enabledSources.map((s) => s.uniqueKey));

    const snapshot: SourcePreferencesSnapshot = {
      sourcePreferences: Object.fromEntries(
        allKnownSources
          .filter((src) => src.uniqueKey !== undefined)
          .map((src) => [src.uniqueKey, enabledKeys.has(src.uniqueKey)])
      ),
    };

    localStorage.setItem(
      LS_SELECTED_INTERNAL_SEARCH_SOURCES_KEY,
      JSON.stringify(snapshot)
    );
  };

  // Initialize sources - load from localStorage or enable all by default
  useEffect(() => {
    if (!sourcesInitialized && availableSources.length > 0) {
      const savedSources = loadSavedSourcePreferences();

      if (savedSources !== null) {
        // Filter out saved sources that no longer exist
        const { sourcePreferences } = savedSources;

        // Helper to check if there is a preference for a key
        const hasPref = (key: string) =>
          Object.prototype.hasOwnProperty.call(sourcePreferences, key);

        // Get sources with no preference
        const newSources = configuredSources.filter((source) => {
          return !hasPref(source.uniqueKey);
        });

        const enabledSources = configuredSources.filter((source) => {
          return (
            hasPref(source.uniqueKey) && sourcePreferences[source.uniqueKey]
          );
        });

        // Merge valid saved sources with new sources (enable new sources by default)
        const mergedSources = [...enabledSources, ...newSources];
        setSelectedSources(mergedSources);

        // Persist the merged state
        persistSourcePreferencesState(mergedSources, configuredSources);
      } else {
        // First time user or invalid data - enable all sources by default
        setSelectedSources(configuredSources);
        persistSourcePreferencesState(configuredSources, configuredSources);
      }
      setSourcesInitialized(true);
    }
  }, [
    availableSources,
    configuredSources,
    sourcesInitialized,
    setSelectedSources,
  ]);

  // Re-initialize when the available source set changes (e.g. switching agents).
  const prevSourcesKey = useRef(availableSources.join(","));
  useEffect(() => {
    const key = availableSources.join(",");
    if (key !== prevSourcesKey.current) {
      prevSourcesKey.current = key;
      setSourcesInitialized(false);
    }
  }, [availableSources]);

  const enableSources = (sources: SourceMetadata[]) => {
    setSelectedSources([...sources]);
    persistSourcePreferencesState(sources, configuredSources);
  };

  const enableAllSources = () => {
    enableSources(configuredSources);
  };

  const disableAllSources = () => {
    setSelectedSources([]);
    persistSourcePreferencesState([], configuredSources);
  };

  const toggleSource = (sourceUniqueKey: string) => {
    const configuredSource = configuredSources.find(
      (s) => s.uniqueKey === sourceUniqueKey
    );
    if (!configuredSource) return;

    const isCurrentlySelected = selectedSources.some(
      (s) => s.uniqueKey === configuredSource.uniqueKey
    );

    let newSources: SourceMetadata[];
    if (isCurrentlySelected) {
      newSources = selectedSources.filter(
        (s) => s.uniqueKey !== configuredSource.uniqueKey
      );
    } else {
      newSources = [...selectedSources, configuredSource];
    }

    setSelectedSources(newSources);
    persistSourcePreferencesState(newSources, configuredSources);
  };

  const isSourceEnabled = (sourceUniqueKey: string) => {
    const configuredSource = configuredSources.find(
      (s) => s.uniqueKey === sourceUniqueKey
    );
    if (!configuredSource) return false;
    return selectedSources.some(
      (s: SourceMetadata) => s.uniqueKey === configuredSource.uniqueKey
    );
  };

  return {
    sourcesInitialized,
    enableSources,
    enableAllSources,
    disableAllSources,
    toggleSource,
    isSourceEnabled,
  };
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
