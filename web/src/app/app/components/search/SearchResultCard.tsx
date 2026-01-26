"use client";

import React from "react";
import { SearchDocWithContent } from "@/lib/search/searchApi";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import Text from "@/refresh-components/texts/Text";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";
import { ValidSources } from "@/lib/types";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import Card from "@/refresh-components/cards/Card";
import { Section } from "@/layouts/general-layouts";

export interface SearchResultCardProps {
  /** The search result document to display */
  document: SearchDocWithContent;
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
    <button onClick={handleClick} className="w-full text-left">
      <Card variant={isLlmSelected ? "primary" : "secondary"}>
        {/* Header: Icon, Title */}
        <Section
          flexDirection="row"
          height="fit"
          alignItems="center"
          justifyContent="start"
          gap={0.5}
        >
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
        </Section>

        {/* Blurb / Match Highlights */}
        <Text as="p" secondaryBody text03 className="line-clamp-3 !m-0">
          {buildDocumentSummaryDisplay(
            document.match_highlights,
            document.blurb
          ) || document.blurb}
        </Text>

        {/* Metadata row */}
        <Section
          flexDirection="row"
          height="fit"
          alignItems="center"
          justifyContent="start"
          gap={0.75}
          wrap
        >
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
        </Section>
      </Card>
    </button>
  );
}

/**
 * Skeleton loading state for SearchResultCard
 */
export function SearchResultCardSkeleton() {
  return (
    <Card variant="secondary">
      <Section height="fit" alignItems="start" gap={0.5}>
        {/* Header skeleton */}
        <Section
          flexDirection="row"
          height="fit"
          alignItems="center"
          justifyContent="start"
          gap={0.5}
        >
          <div className="w-[18px] h-[18px] bg-background-neutral-01 rounded animate-pulse" />
          <div className="h-4 bg-background-neutral-01 rounded w-3/4 animate-pulse" />
        </Section>

        {/* Blurb skeleton */}
        <Section height="fit" alignItems="start" gap={0.375}>
          <div className="h-3 bg-background-neutral-01 rounded w-full animate-pulse" />
          <div className="h-3 bg-background-neutral-01 rounded w-5/6 animate-pulse" />
          <div className="h-3 bg-background-neutral-01 rounded w-4/6 animate-pulse" />
        </Section>

        {/* Metadata skeleton */}
        <Section
          flexDirection="row"
          height="fit"
          alignItems="center"
          justifyContent="start"
          gap={0.75}
        >
          <div className="h-3 bg-background-neutral-01 rounded w-16 animate-pulse" />
          <div className="h-3 bg-background-neutral-01 rounded w-24 animate-pulse" />
        </Section>
      </Section>
    </Card>
  );
}
