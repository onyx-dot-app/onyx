"use client";

import { useEffect, useMemo, useState } from "react";
import { BaseFilters, SearchDocWithContent } from "@/lib/search/searchApi";
import { MinimalOnyxDocument, SourceMetadata } from "@/lib/search/interfaces";
import SearchCard from "@/sections/cards/SearchCard";
import Separator from "@/refresh-components/Separator";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import { getSourceMetadata } from "@/lib/sources";
import { Tag, ValidSources } from "@/lib/types";
import { useTags } from "@/lib/hooks/useTags";
import { SourceIcon } from "@/components/SourceIcon";
import Text from "@/refresh-components/texts/Text";
import LineItem from "@/refresh-components/buttons/LineItem";
import { Section } from "@/layouts/general-layouts";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import { SvgCheck, SvgClock, SvgTag } from "@opal/icons";
import FilterButton from "@/refresh-components/buttons/FilterButton";

// ============================================================================
// Types
// ============================================================================

export interface SearchResultsProps {
  /** Search results to display */
  results: SearchDocWithContent[];
  /** Document IDs that the LLM selected as most relevant */
  llmSelectedDocIds?: string[] | null;
  /** Callback when a document is clicked */
  onDocumentClick: (doc: MinimalOnyxDocument) => void;
  /** Re-run the search with updated server-side filters */
  onRefineSearch: (filters: BaseFilters) => Promise<void>;
}

// ============================================================================
// Constants
// ============================================================================

type TimeFilter = "day" | "week" | "month" | "year";

const TIME_FILTER_OPTIONS: { value: TimeFilter; label: string }[] = [
  { value: "day", label: "Past 24 hours" },
  { value: "week", label: "Past week" },
  { value: "month", label: "Past month" },
  { value: "year", label: "Past year" },
];

// ============================================================================
// Helpers
// ============================================================================

function getTimeFilterDate(filter: TimeFilter): Date | null {
  const now = new Date();
  switch (filter) {
    case "day":
      return new Date(now.getTime() - 24 * 60 * 60 * 1000);
    case "week":
      return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    case "month":
      return new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    case "year":
      return new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000);
    default:
      return null;
  }
}

// ============================================================================
// SearchResults Component (default export)
// ============================================================================

/**
 * Component for displaying search results with source filter sidebar.
 */
export default function SearchUI({
  results,
  llmSelectedDocIds,
  onDocumentClick,
  onRefineSearch,
}: SearchResultsProps) {
  // Available tags from backend
  const { tags: availableTags } = useTags();

  // Filter state
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [timeFilter, setTimeFilter] = useState<TimeFilter | null>(null);
  const [timeFilterOpen, setTimeFilterOpen] = useState(false);
  const [selectedTags, setSelectedTags] = useState<Tag[]>([]);
  const [tagFilterOpen, setTagFilterOpen] = useState(false);

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

  // Reset source filter when results change
  useEffect(() => {
    setSelectedSources([]);
  }, [results]);
  const [ownerFilter, setOwnerFilter] = useState<string>("everyone");
  const [tagFilter, setTagFilter] = useState<string>("all-tags");

  // Create a set for fast lookup of LLM-selected docs
  const llmSelectedSet = new Set(llmSelectedDocIds ?? []);

  // Extract unique owners from results
  const uniqueOwners = useMemo(() => {
    const owners = new Set<string>();
    for (const doc of results) {
      if (doc.primary_owners) {
        for (const owner of doc.primary_owners) {
          owners.add(owner);
        }
      }
    }
    return Array.from(owners).sort();
  }, [results]);

  // Extract unique tags from results
  const uniqueTags = useMemo(() => {
    const tags = new Set<string>();
    for (const doc of results) {
      if (doc.metadata?.tags) {
        const docTags = Array.isArray(doc.metadata.tags)
          ? doc.metadata.tags
          : [doc.metadata.tags];
        for (const tag of docTags) {
          tags.add(tag);
        }
      }
    }
    return Array.from(tags).sort();
  }, [results]);

  // Filter and sort results
  const filteredAndSortedResults = useMemo(() => {
    const filtered = results.filter((doc) => {
      // Source filter (client-side)
      if (selectedSources.length > 0) {
        if (!doc.source_type || !selectedSources.includes(doc.source_type)) {
          return false;
        }
      }

      // Owner filter
      if (ownerFilter !== "everyone") {
        if (!doc.primary_owners || !doc.primary_owners.includes(ownerFilter)) {
          return false;
        }
      }

      // Tag filter
      if (tagFilter !== "all-tags") {
        if (!doc.metadata?.tags) return false;
        const docTags = Array.isArray(doc.metadata.tags)
          ? doc.metadata.tags
          : [doc.metadata.tags];
        if (!docTags.includes(tagFilter)) return false;
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
  }, [results, selectedSources, ownerFilter, tagFilter, llmSelectedSet]);

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
    if (selectedSources.includes(source)) {
      setSelectedSources(selectedSources.filter((s) => s !== source));
    } else {
      setSelectedSources([...selectedSources, source]);
    }
  };

  return (
    <div
      className="h-full w-full grid min-h-0 gap-x-4"
      style={{ gridTemplateColumns: "3fr 1fr", gridTemplateRows: "auto 1fr" }}
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
                {availableTags.map((tag) => {
                  const isSelected = selectedTags.some(
                    (t) =>
                      t.tag_key === tag.tag_key && t.tag_value === tag.tag_value
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
        {filteredAndSortedResults.length > 0 ? (
          filteredAndSortedResults.map((doc) => (
            <SearchCard
              key={`${doc.document_id}-${doc.chunk_ind}`}
              document={doc}
              isLlmSelected={llmSelectedSet.has(doc.document_id)}
              onDocumentClick={onDocumentClick}
            />
          ))
        ) : (
          <EmptyMessage
            title="No documents found"
            description="Try searching for something else"
          />
        )}
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
  );
}
