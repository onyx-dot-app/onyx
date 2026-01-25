"use client";

import React from "react";
import { SearchDocWithContent } from "@/lib/search/searchApi";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { SearchResultCard, SearchResultCardSkeleton } from "./SearchResultCard";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { SvgBubbleText, SvgSearch } from "@opal/icons";

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
  /** Callback when user wants to ask about the search results */
  onAskAboutResults: () => void;
}

/**
 * Panel component for displaying search results.
 *
 * Shows a grid of search result cards with loading and empty states.
 * Includes an "Ask about these results" button to transition to chat.
 */
export function SearchResultsPanel({
  query,
  executedQueries,
  results,
  llmSelectedDocIds,
  isLoading,
  error,
  onDocumentClick,
  onAskAboutResults,
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
    <div className="flex flex-col gap-4 w-full max-w-4xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex flex-row items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <SvgSearch className="w-5 h-5 text-03" />
            <Text as="p" headingH3 className="!m-0">
              Search Results
            </Text>
          </div>

          {!isLoading && !error && (
            <Text as="p" secondaryBody text03 className="!m-0">
              {results.length === 0
                ? `No results found for "${query}"`
                : `Found ${results.length} result${
                    results.length === 1 ? "" : "s"
                  } for "${query}"`}
            </Text>
          )}

          {/* Show executed query expansions if different from original */}
          {executedQueries &&
            executedQueries.length > 0 &&
            executedQueries.some((q) => q !== query) && (
              <Text as="p" figureSmallLabel text03 className="!m-0">
                Also searched:{" "}
                {executedQueries.filter((q) => q !== query).join(", ")}
              </Text>
            )}
        </div>

        {/* Ask about results button */}
        {results.length > 0 && (
          <Button
            onClick={onAskAboutResults}
            leftIcon={SvgBubbleText}
            secondary
          >
            Ask about these results
          </Button>
        )}
      </div>

      {/* Error state */}
      {error && (
        <div className="bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <Text
            as="p"
            mainUiBody
            className="text-red-700 dark:text-red-300 !m-0"
          >
            Search failed: {error}
          </Text>
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <SearchResultCardSkeleton key={i} />
          ))}
        </div>
      )}

      {/* Results grid */}
      {!isLoading && !error && results.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {sortedResults.map((doc, index) => (
            <SearchResultCard
              key={`${doc.document_id}-${doc.chunk_ind}`}
              document={doc}
              rank={index + 1}
              isLlmSelected={llmSelectedSet.has(doc.document_id)}
              onDocumentClick={onDocumentClick}
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && results.length === 0 && query && (
        <EmptySearchState query={query} onAskAboutResults={onAskAboutResults} />
      )}
    </div>
  );
}

interface EmptySearchStateProps {
  query: string;
  onAskAboutResults: () => void;
}

function EmptySearchState({ query, onAskAboutResults }: EmptySearchStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-4">
      <div className="w-16 h-16 rounded-full bg-neutral-100 dark:bg-neutral-800 flex items-center justify-center">
        <SvgSearch className="w-8 h-8 text-neutral-400" />
      </div>

      <div className="text-center max-w-md">
        <Text as="p" headingH3 className="!m-0 mb-2">
          No results found
        </Text>
        <Text as="p" secondaryBody text03 className="!m-0">
          We couldn&apos;t find any documents matching &quot;{query}&quot;. Try
          adjusting your search terms or ask the AI assistant for help.
        </Text>
      </div>

      <Button onClick={onAskAboutResults} leftIcon={SvgBubbleText}>
        Ask AI about &quot;{query}&quot;
      </Button>
    </div>
  );
}

/**
 * Skeleton loading state for the entire search panel
 */
export function SearchResultsPanelSkeleton() {
  return (
    <div className="flex flex-col gap-4 w-full max-w-4xl mx-auto px-4 py-6 animate-pulse">
      {/* Header skeleton */}
      <div className="flex flex-row items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <div className="h-6 bg-neutral-200 dark:bg-neutral-700 rounded w-40" />
          <div className="h-4 bg-neutral-200 dark:bg-neutral-700 rounded w-60" />
        </div>
        <div className="h-9 bg-neutral-200 dark:bg-neutral-700 rounded w-48" />
      </div>

      {/* Results grid skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <SearchResultCardSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}
