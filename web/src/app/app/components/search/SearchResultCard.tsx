"use client";

import React from "react";
import { SearchDocWithContent } from "@/lib/search/searchApi";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import Text from "@/refresh-components/texts/Text";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";
import { ValidSources } from "@/lib/types";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { Card } from "@/components/ui/card";

export interface SearchResultCardProps {
  /** The search result document to display */
  document: SearchDocWithContent;
  /** Optional rank/position in search results */
  rank?: number;
  /** Whether this result was selected by the LLM as relevant */
  isLlmSelected?: boolean;
  /** Callback when the document is clicked */
  onDocumentClick: (doc: MinimalOnyxDocument) => void;
}

/**
 * Card component for displaying a single search result.
 *
 * Shows the document title, source icon, blurb/highlights, and metadata.
 * Clicking the card opens the document preview.
 */
export function SearchResultCard({
  document,
  rank,
  isLlmSelected,
  onDocumentClick,
}: SearchResultCardProps) {
  const isWebSource =
    document.is_internet || document.source_type === ValidSources.Web;

  const handleClick = () => {
    onDocumentClick({
      document_id: document.document_id,
      semantic_identifier: document.semantic_identifier,
    });
  };

  // Format the score as a percentage if available
  const scoreDisplay =
    document.score != null ? `${Math.round(document.score * 100)}%` : null;

  return (
    <Card
      className={`
        shadow-00 hover:bg-background-tint-00 cursor-pointer transition-colors
        ${isLlmSelected ? "ring-2 ring-accent-500 ring-opacity-50" : ""}
      `}
    >
      <button
        onClick={handleClick}
        className="w-full p-4 flex flex-col gap-2 text-left"
      >
        {/* Header: Rank, Icon, Title */}
        <div className="flex flex-row gap-2 items-center w-full">
          {rank !== undefined && (
            <Text
              as="span"
              figureSmallValue
              text03
              className="min-w-[1.5rem] text-center"
            >
              {rank}
            </Text>
          )}

          {isWebSource && document.link ? (
            <WebResultIcon url={document.link} size={18} />
          ) : (
            <SourceIcon sourceType={document.source_type} iconSize={18} />
          )}

          <Text
            as="p"
            mainUiBody
            text04
            className="truncate flex-1 !m-0 font-medium"
          >
            {document.semantic_identifier || document.document_id}
          </Text>

          {isLlmSelected && (
            <span className="text-xs bg-accent-100 text-accent-700 px-2 py-0.5 rounded-full">
              Recommended
            </span>
          )}
        </div>

        {/* Blurb / Match Highlights */}
        <Text as="p" secondaryBody text03 className="line-clamp-3 !m-0">
          {buildDocumentSummaryDisplay(
            document.match_highlights,
            document.blurb
          ) || document.blurb}
        </Text>

        {/* Metadata row */}
        <div className="flex flex-row items-center gap-3 flex-wrap">
          {/* Source type badge */}
          <Text as="span" figureSmallLabel text03 className="capitalize">
            {document.source_type.replace(/_/g, " ")}
          </Text>

          {/* Updated date */}
          {document.updated_at &&
            !isNaN(new Date(document.updated_at).getTime()) && (
              <Text as="span" figureSmallLabel text03>
                Updated {new Date(document.updated_at).toLocaleDateString()}
              </Text>
            )}

          {/* Relevance score */}
          {scoreDisplay && (
            <Text as="span" figureSmallLabel text03>
              Relevance: {scoreDisplay}
            </Text>
          )}
        </div>
      </button>
    </Card>
  );
}

/**
 * Skeleton loading state for SearchResultCard
 */
export function SearchResultCardSkeleton() {
  return (
    <Card className="shadow-00 animate-pulse">
      <div className="w-full p-4 flex flex-col gap-2">
        {/* Header skeleton */}
        <div className="flex flex-row gap-2 items-center">
          <div className="w-[18px] h-[18px] bg-neutral-200 dark:bg-neutral-700 rounded" />
          <div className="h-4 bg-neutral-200 dark:bg-neutral-700 rounded w-3/4" />
        </div>

        {/* Blurb skeleton */}
        <div className="space-y-1.5">
          <div className="h-3 bg-neutral-200 dark:bg-neutral-700 rounded w-full" />
          <div className="h-3 bg-neutral-200 dark:bg-neutral-700 rounded w-5/6" />
          <div className="h-3 bg-neutral-200 dark:bg-neutral-700 rounded w-4/6" />
        </div>

        {/* Metadata skeleton */}
        <div className="flex flex-row gap-3">
          <div className="h-3 bg-neutral-200 dark:bg-neutral-700 rounded w-16" />
          <div className="h-3 bg-neutral-200 dark:bg-neutral-700 rounded w-24" />
        </div>
      </div>
    </Card>
  );
}
