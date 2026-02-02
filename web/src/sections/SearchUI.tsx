"use client";

import { useMemo, useState } from "react";
import { SearchDocWithContent } from "@/lib/search/searchApi";
import { MinimalOnyxDocument, SourceMetadata } from "@/lib/search/interfaces";
import SearchCard from "@/sections/cards/SearchCard";
import Separator from "@/refresh-components/Separator";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import { getSourceMetadata } from "@/lib/sources";
import { ValidSources } from "@/lib/types";
import { SourceIcon } from "@/components/SourceIcon";
import Text from "@/refresh-components/texts/Text";
import LineItem from "@/refresh-components/buttons/LineItem";

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
  /** Selected sources for filtering */
  selectedSources: string[];
  /** Callback when source selection changes */
  onSourceChange: (sources: string[]) => void;
}

// ============================================================================
// Constants
// ============================================================================

type TimeFilter = "all-time" | "day" | "week" | "month" | "year";

const TIME_FILTER_OPTIONS: { value: TimeFilter; label: string }[] = [
  { value: "all-time", label: "All Time" },
  { value: "day", label: "Past 24 hours" },
  { value: "week", label: "Past week" },
  { value: "month", label: "Past month" },
  { value: "year", label: "Past year" },
];

// ============================================================================
// Helpers
// ============================================================================

function getTimeFilterDate(filter: TimeFilter): Date | null {
  if (filter === "all-time") return null;

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
  selectedSources,
  onSourceChange,
}: SearchResultsProps) {
  // Filter state
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("all-time");
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
    const timeThreshold = getTimeFilterDate(timeFilter);

    const filtered = results.filter((doc) => {
      // Source filter
      if (selectedSources.length > 0) {
        if (!doc.source_type || !selectedSources.includes(doc.source_type)) {
          return false;
        }
      }

      // Time filter
      if (timeThreshold && doc.updated_at) {
        const docDate = new Date(doc.updated_at);
        if (docDate < timeThreshold) return false;
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
  }, [
    results,
    selectedSources,
    timeFilter,
    ownerFilter,
    tagFilter,
    llmSelectedSet,
  ]);

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
      onSourceChange(selectedSources.filter((s) => s !== source));
    } else {
      onSourceChange([...selectedSources, source]);
    }
  };

  return (
    <div className="h-full w-full flex flex-row gap-2">
      {/* Results list */}
      <div className="flex-[3] min-w-0 flex flex-col min-h-0 h-full overflow-y-scroll py-3">
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

      {/* Source filter sidebar */}
      <div className="flex-1 h-full overflow-y-auto py-4 flex flex-col gap-4 px-1">
        <div className="py-4 h-[2.75rem] px-2">
          <Text text03 mainUiMuted>
            {results.length} Results
          </Text>
        </div>

        <Separator noPadding />

        <div className="flex flex-col gap-1">
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
        </div>
      </div>
    </div>
  );
}
