"use client";

import React from "react";
import { SearchDocWithContent } from "@/lib/search/searchApi";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { SearchResultCard, SearchResultCardSkeleton } from "./SearchResultCard";
import Text from "@/refresh-components/texts/Text";
import { SvgSearch } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";

export interface SearchResultsPanelProps {
  /** The search query that was executed */
  query: string;
  /** List of query expansions that were executed */
  executedQueries?: string[];
  /** Search results to display */
  results: SearchDocWithContent[];
  /** Document IDs that the LLM selected as most relevant */
  llmSelectedDocIds?: string[] | null;
  /** Whether search is currently loading */
  isLoading: boolean;
  /** Error message if search failed */
  error?: string | null;
  /** Callback when a document is clicked */
  onDocumentClick: (doc: MinimalOnyxDocument) => void;
}

const MAX_WIDTH_CLASS = "w-full max-w-4xl";

/**
 * Panel component for displaying search results.
 *
 * Shows a vertical list of search result cards with loading and empty states.
 */
export function SearchResultsPanel({
  query,
  executedQueries,
  results,
  llmSelectedDocIds,
  isLoading,
  error,
  onDocumentClick,
}: SearchResultsPanelProps) {
  // Create a set for fast lookup of LLM-selected docs
  const llmSelectedSet = new Set(llmSelectedDocIds ?? []);

  // Sort results: LLM-selected first, then by score
  const sortedResults = [...results].sort((a, b) => {
    const aSelected = llmSelectedSet.has(a.document_id);
    const bSelected = llmSelectedSet.has(b.document_id);

    if (aSelected && !bSelected) return -1;
    if (!aSelected && bSelected) return 1;

    // Both selected or both not selected: sort by score
    return (b.score ?? 0) - (a.score ?? 0);
  });

  return (
    <Section alignItems="center" justifyContent="start" gap={1} padding={1}>
      {/* Error state */}
      {error && (
        <div className={MAX_WIDTH_CLASS}>
          <div className="w-full bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg p-4">
            <Text
              as="p"
              mainUiBody
              className="text-red-700 dark:text-red-300 !m-0"
            >
              Search failed: {error}
            </Text>
          </div>
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div className={MAX_WIDTH_CLASS}>
          <Section height="fit" gap={0.75}>
            {Array.from({ length: 4 }).map((_, i) => (
              <SearchResultCardSkeleton key={i} />
            ))}
          </Section>
        </div>
      )}

      {/* Results list */}
      {!isLoading && !error && results.length > 0 && (
        <div className={MAX_WIDTH_CLASS}>
          <Section height="fit" gap={0.75}>
            {sortedResults.map((doc) => (
              <SearchResultCard
                key={`${doc.document_id}-${doc.chunk_ind}`}
                document={doc}
                isLlmSelected={llmSelectedSet.has(doc.document_id)}
                onDocumentClick={onDocumentClick}
              />
            ))}
          </Section>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && results.length === 0 && query && (
        <EmptySearchState query={query} />
      )}
    </Section>
  );
}

interface EmptySearchStateProps {
  query: string;
}

function EmptySearchState({ query }: EmptySearchStateProps) {
  return (
    <div className={MAX_WIDTH_CLASS}>
      <Section height="fit" gap={1} padding={3}>
        <div className="w-16 h-16 rounded-full bg-background-neutral-01 flex items-center justify-center">
          <SvgSearch className="w-8 h-8 stroke-text-02" />
        </div>

        <Section height="fit" gap={0.5}>
          <Text as="p" headingH3 className="!m-0">
            No results found
          </Text>
          <Text
            as="p"
            secondaryBody
            text03
            className="!m-0 text-center max-w-md"
          >
            We couldn&apos;t find any documents matching &quot;{query}&quot;.
            Try adjusting your search terms.
          </Text>
        </Section>
      </Section>
    </div>
  );
}

/**
 * Skeleton loading state for the entire search panel
 */
export function SearchResultsPanelSkeleton() {
  return (
    <Section alignItems="center" justifyContent="start" gap={1} padding={1}>
      <div className={MAX_WIDTH_CLASS}>
        <Section height="fit" gap={0.75}>
          {Array.from({ length: 4 }).map((_, i) => (
            <SearchResultCardSkeleton key={i} />
          ))}
        </Section>
      </div>
    </Section>
  );
}
