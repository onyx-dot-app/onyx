"use client";

import { useMemo, useState } from "react";
import { SearchDocWithContent } from "@/lib/search/searchApi";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import SearchCard from "@/sections/cards/SearchCard";
import { Section } from "@/layouts/general-layouts";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Separator from "@/refresh-components/Separator";
import Spacer from "@/refresh-components/Spacer";
import { SvgClock, SvgTag, SvgUser } from "@opal/icons";
import EmptyMessage from "@/refresh-components/EmptyMessage";

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
 * Component for displaying search results with filters.
 */
export default function SearchResults({
  results,
  llmSelectedDocIds,
  onDocumentClick,
  selectedSources,
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

  return (
    <div className="flex flex-col h-full w-full max-w-[var(--main-app-width)]">
      <Spacer rem={1.5} />

      {/* Filters - fixed at top */}
      {/*<div className="flex flex-col flex-shrink-0 gap-4">
        <div className="flex flex-row items-center justify-start">
          <InputSelect
            value={timeFilter}
            onValueChange={(value) => setTimeFilter(value as TimeFilter)}
          >
            <InputSelect.Trigger placeholder="Time" />
            <InputSelect.Content>
              {TIME_FILTER_OPTIONS.map((option) => (
                <InputSelect.Item
                  key={option.value}
                  value={option.value}
                  icon={SvgClock}
                >
                  {option.label}
                </InputSelect.Item>
              ))}
            </InputSelect.Content>
          </InputSelect>

          <InputSelect value={ownerFilter} onValueChange={setOwnerFilter}>
            <InputSelect.Trigger />
            <InputSelect.Content>
              <InputSelect.Item value="everyone" icon={SvgUser}>
                Everyone
              </InputSelect.Item>
              {uniqueOwners.map((owner) => (
                <InputSelect.Item key={owner} value={owner} icon={SvgUser}>
                  {owner}
                </InputSelect.Item>
              ))}
            </InputSelect.Content>
          </InputSelect>

          <InputSelect value={tagFilter} onValueChange={setTagFilter}>
            <InputSelect.Trigger placeholder="Tags" />
            <InputSelect.Content>
              <InputSelect.Item value="all-tags" icon={SvgTag}>
                All Tags
              </InputSelect.Item>
              {uniqueTags.map((tag) => (
                <InputSelect.Item key={tag} value={tag} icon={SvgTag}>
                  {tag}
                </InputSelect.Item>
              ))}
            </InputSelect.Content>
          </InputSelect>
        </div>

        <Separator noPadding />
      </div>*/}

      {/* Results list */}
      <div className="flex-1 min-h-0 overflow-y-auto py-4">
        <Section
          gap={0.5}
          justifyContent={
            filteredAndSortedResults.length > 0 ? "start" : "center"
          }
        >
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
        </Section>
      </div>
    </div>
  );
}
