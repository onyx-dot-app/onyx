"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BaseFilters,
  MinimalOnyxDocument,
  SourceMetadata,
} from "@/lib/search/interfaces";
import SearchCard from "@/ee/sections/SearchCard";
import Pagination from "@/refresh-components/Pagination";
import Separator from "@/refresh-components/Separator";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import { getSourceMetadata } from "@/lib/sources";
import { Tag, ValidSources } from "@/lib/types";
import { getTimeFilterDate, TimeFilter } from "@/lib/time";
import useTags from "@/hooks/useTags";
import { SourceIcon } from "@/components/SourceIcon";
import Text from "@/refresh-components/texts/Text";
import LineItem from "@/refresh-components/buttons/LineItem";
import { Section } from "@/layouts/general-layouts";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import { SvgCheck, SvgClock, SvgTag } from "@opal/icons";
import FilterButton from "@/refresh-components/buttons/FilterButton";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import useFilter from "@/hooks/useFilter";
import { useQueryController } from "@/providers/QueryControllerProvider";
import { toast } from "@/hooks/useToast";

// ============================================================================
// Types
// ============================================================================

export interface SearchResultsProps {
  /** Callback when a document is clicked */
  onDocumentClick: (doc: MinimalOnyxDocument) => void;
}

// ============================================================================
// Constants
// ============================================================================

const RESULTS_PER_PAGE = 20;

const TIME_FILTER_OPTIONS: { value: TimeFilter; label: string }[] = [
  { value: "day", label: "Past 24 hours" },
  { value: "week", label: "Past week" },
  { value: "month", label: "Past month" },
  { value: "year", label: "Past year" },
];

// ============================================================================
// SearchResults Component (default export)
// ============================================================================

/**
 * Component for displaying search results with source filter sidebar.
 */
export default function SearchUI({ onDocumentClick }: SearchResultsProps) {
  // Available tags from backend
  const { tags: availableTags } = useTags();
  const {
    searchResults: results,
    llmSelectedDocIds,
    error,
    refineSearch: onRefineSearch,
  } = useQueryController();
  const prevErrorRef = useRef<string | null>(null);

  // Show a toast notification when a new error occurs
  useEffect(() => {
    if (error && error !== prevErrorRef.current) {
      toast.error(error);
    }
    prevErrorRef.current = error;
  }, [error]);

  // Filter state
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [timeFilter, setTimeFilter] = useState<TimeFilter | null>(null);
  const [timeFilterOpen, setTimeFilterOpen] = useState(false);
  const [selectedTags, setSelectedTags] = useState<Tag[]>([]);
  const [tagFilterOpen, setTagFilterOpen] = useState(false);

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);

  const tagExtractor = useCallback(
    (tag: Tag) => `${tag.tag_key} ${tag.tag_value}`,
    []
  );
  const {
    query: tagQuery,
    setQuery: setTagQuery,
    filtered: filteredTags,
  } = useFilter(availableTags, tagExtractor);

  // Build the combined server-side filters from current state
  const buildFilters = (
    overrides: { time?: TimeFilter | null; tags?: Tag[] } = {}
  ): BaseFilters => {
    const time = overrides.time !== undefined ? overrides.time : timeFilter;
    const tags = overrides.tags !== undefined ? overrides.tags : selectedTags;
    const cutoff = time ? getTimeFilterDate(time) : null;
    return {
      time_cutoff: cutoff?.toISOString() ?? null,
      tags:
        tags.length > 0
          ? tags.map((t) => ({ tag_key: t.tag_key, tag_value: t.tag_value }))
          : null,
    };
  };

  // Reset source filter and pagination when results change
  useEffect(() => {
    setSelectedSources([]);
    setCurrentPage(1);
  }, [results]);

  // Create a set for fast lookup of LLM-selected docs
  const llmSelectedSet = new Set(llmSelectedDocIds ?? []);

  // Filter and sort results
  const filteredAndSortedResults = useMemo(() => {
    const filtered = results.filter((doc) => {
      // Source filter (client-side)
      if (selectedSources.length > 0) {
        if (!doc.source_type || !selectedSources.includes(doc.source_type)) {
          return false;
        }
      }

      return true;
    });

    // Sort: LLM-selected first, then by score
    return filtered.sort((a, b) => {
      const aSelected = llmSelectedSet.has(a.document_id);
      const bSelected = llmSelectedSet.has(b.document_id);

      if (aSelected && !bSelected) return -1;
      if (!aSelected && bSelected) return 1;

      return (b.score ?? 0) - (a.score ?? 0);
    });
  }, [results, selectedSources, llmSelectedSet]);

  // Pagination
  const totalPages = Math.max(
    1,
    Math.ceil(filteredAndSortedResults.length / RESULTS_PER_PAGE)
  );
  const paginatedResults = useMemo(() => {
    const start = (currentPage - 1) * RESULTS_PER_PAGE;
    return filteredAndSortedResults.slice(start, start + RESULTS_PER_PAGE);
  }, [filteredAndSortedResults, currentPage]);

  // Extract unique sources with metadata for the source filter
  const sourcesWithMeta = useMemo(() => {
    const sourceMap = new Map<
      string,
      { meta: SourceMetadata; count: number }
    >();

    for (const doc of results) {
      if (doc.source_type) {
        const existing = sourceMap.get(doc.source_type);
        if (existing) {
          existing.count++;
        } else {
          sourceMap.set(doc.source_type, {
            meta: getSourceMetadata(doc.source_type as ValidSources),
            count: 1,
          });
        }
      }
    }

    return Array.from(sourceMap.entries())
      .map(([source, data]) => ({
        source,
        ...data,
      }))
      .sort((a, b) => b.count - a.count);
  }, [results]);

  const handleSourceToggle = (source: string) => {
    setCurrentPage(1);
    if (selectedSources.includes(source)) {
      setSelectedSources(selectedSources.filter((s) => s !== source));
    } else {
      setSelectedSources([...selectedSources, source]);
    }
  };

  return (
    <>
      <div
        className="flex-1 min-h-0 w-full grid gap-x-4"
        style={{
          gridTemplateColumns: "3fr 1fr",
          gridTemplateRows: "auto 1fr auto",
        }}
      >
        {/* Top-left: Search filters */}
        <div className="row-start-1 col-start-1 flex flex-col justify-end gap-3">
          <div className="flex flex-row gap-2">
            {/* Time filter */}
            <Popover open={timeFilterOpen} onOpenChange={setTimeFilterOpen}>
              <Popover.Trigger asChild>
                <FilterButton
                  leftIcon={SvgClock}
                  active={!!timeFilter}
                  onClear={() => {
                    setTimeFilter(null);
                    onRefineSearch(buildFilters({ time: null }));
                  }}
                >
                  {TIME_FILTER_OPTIONS.find((o) => o.value === timeFilter)
                    ?.label ?? "All Time"}
                </FilterButton>
              </Popover.Trigger>
              <Popover.Content align="start" width="md">
                <PopoverMenu>
                  {TIME_FILTER_OPTIONS.map((opt) => (
                    <LineItem
                      key={opt.value}
                      onClick={() => {
                        setTimeFilter(opt.value);
                        setTimeFilterOpen(false);
                        onRefineSearch(buildFilters({ time: opt.value }));
                      }}
                      selected={timeFilter === opt.value}
                      icon={timeFilter === opt.value ? SvgCheck : SvgClock}
                    >
                      {opt.label}
                    </LineItem>
                  ))}
                </PopoverMenu>
              </Popover.Content>
            </Popover>

            {/* Tag filter */}
            <Popover open={tagFilterOpen} onOpenChange={setTagFilterOpen}>
              <Popover.Trigger asChild>
                <FilterButton
                  leftIcon={SvgTag}
                  active={selectedTags.length > 0}
                  onClear={() => {
                    setSelectedTags([]);
                    onRefineSearch(buildFilters({ tags: [] }));
                  }}
                >
                  {selectedTags.length > 0
                    ? `${selectedTags.length} Tag${
                        selectedTags.length > 1 ? "s" : ""
                      }`
                    : "Tags"}
                </FilterButton>
              </Popover.Trigger>
              <Popover.Content align="start" width="lg">
                <PopoverMenu>
                  <InputTypeIn
                    leftSearchIcon
                    placeholder="Filter tags..."
                    value={tagQuery}
                    onChange={(e) => setTagQuery(e.target.value)}
                    onClear={() => setTagQuery("")}
                    variant="internal"
                  />
                  {filteredTags.map((tag) => {
                    const isSelected = selectedTags.some(
                      (t) =>
                        t.tag_key === tag.tag_key &&
                        t.tag_value === tag.tag_value
                    );
                    return (
                      <LineItem
                        key={`${tag.tag_key}=${tag.tag_value}`}
                        onClick={() => {
                          const next = isSelected
                            ? selectedTags.filter(
                                (t) =>
                                  t.tag_key !== tag.tag_key ||
                                  t.tag_value !== tag.tag_value
                              )
                            : [...selectedTags, tag];
                          setSelectedTags(next);
                          onRefineSearch(buildFilters({ tags: next }));
                        }}
                        selected={isSelected}
                        icon={isSelected ? SvgCheck : SvgTag}
                      >
                        {tag.tag_value}
                      </LineItem>
                    );
                  })}
                </PopoverMenu>
              </Popover.Content>
            </Popover>
          </div>

          <Separator noPadding />
        </div>

        {/* Top-right: Number of results */}
        <div className="row-start-1 col-start-2 flex flex-col justify-end gap-3">
          <Section alignItems="start">
            <Text text03 mainUiMuted>
              {results.length} Results
            </Text>
          </Section>

          <Separator noPadding />
        </div>

        {/* Bottom-left: Search results */}
        <div className="row-start-2 col-start-1 min-h-0 overflow-y-scroll py-3 flex flex-col gap-2">
          {error ? (
            <EmptyMessage title="Search failed" description={error} />
          ) : paginatedResults.length > 0 ? (
            <>
              {paginatedResults.map((doc) => (
                <SearchCard
                  key={`${doc.document_id}-${doc.chunk_ind}`}
                  document={doc}
                  isLlmSelected={llmSelectedSet.has(doc.document_id)}
                  onDocumentClick={onDocumentClick}
                />
              ))}
            </>
          ) : (
            <EmptyMessage
              title="No documents found"
              description="Try searching for something else"
            />
          )}
        </div>

        {/* Pagination */}
        <div className="row-start-3 col-start-1 col-span-2 pt-3">
          <Pagination
            currentPage={currentPage}
            totalPages={totalPages}
            onPageChange={setCurrentPage}
          />
        </div>

        {/* Bottom-right: Source filter */}
        <div className="row-start-2 col-start-2 min-h-0 overflow-y-auto flex flex-col gap-4 px-1 py-3">
          <Section gap={0.25} height="fit">
            {sourcesWithMeta.map(({ source, meta, count }) => (
              <LineItem
                key={source}
                icon={(props) => (
                  <SourceIcon
                    sourceType={source as ValidSources}
                    iconSize={16}
                    {...props}
                  />
                )}
                onClick={() => handleSourceToggle(source)}
                selected={selectedSources.includes(source)}
                emphasized
                rightChildren={<Text text03>{count}</Text>}
              >
                {meta.displayName}
              </LineItem>
            ))}
          </Section>
        </div>
      </div>
    </>
  );
}
