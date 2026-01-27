"use client";

import { SearchDocWithContent } from "@/lib/search/searchApi";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import SearchCard from "@/sections/cards/SearchCard";
import { Section } from "@/layouts/general-layouts";

export interface SearchUIProps {
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

/**
 * Panel component for displaying search results.
 *
 * Shows a vertical list of search result cards with loading and empty states.
 */
export default function SearchUI({
  results,
  llmSelectedDocIds,
  isLoading,
  error,
  onDocumentClick,
}: SearchUIProps) {
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
    <Section alignItems="center" justifyContent="start" gap={1}>
      {/* Results list */}
      {!isLoading && !error && results.length > 0 && (
        <div className="w-[var(--main-app-width)]">
          <Section height="fit" gap={0.75}>
            {sortedResults.map((doc) => (
              <SearchCard
                key={`${doc.document_id}-${doc.chunk_ind}`}
                document={doc}
                isLlmSelected={llmSelectedSet.has(doc.document_id)}
                onDocumentClick={onDocumentClick}
              />
            ))}
          </Section>
        </div>
      )}
    </Section>
  );
}
