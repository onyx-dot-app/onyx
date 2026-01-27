"use client";

import { SearchDocWithContent } from "@/lib/search/searchApi";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import Text from "@/refresh-components/texts/Text";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";
import { ValidSources } from "@/lib/types";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { Section } from "@/layouts/general-layouts";
import Hoverable from "@/refresh-components/Hoverable";
import Truncated from "@/refresh-components/texts/Truncated";
import { formatRelativeTime } from "@/lib/utils";

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
export default function SearchCard({
  document,
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
    <Hoverable onClick={handleClick}>
      <Section alignItems="start" gap={0} padding={0.25}>
        {/* Title Row */}
        <Section
          flexDirection="row"
          justifyContent="start"
          gap={0.25}
          padding={0.25}
        >
          {isWebSource && document.link ? (
            <WebResultIcon url={document.link} size={18} />
          ) : (
            <SourceIcon sourceType={document.source_type} iconSize={16} />
          )}

          <Truncated mainUiAction className="text-left">
            {document.semantic_identifier}
          </Truncated>
        </Section>

        {/* Body Row */}
        <div className="px-1 pb-1">
          <Section alignItems="start" gap={0.25}>
            {/* Metadata */}
            <Section flexDirection="row" justifyContent="start" gap={0.25}>
              {document.primary_owners &&
                document.primary_owners.length > 0 && (
                  <Text figureSmallLabel text03>
                    {document.primary_owners[0]}
                  </Text>
                )}
              {document.metadata?.tags &&
                (Array.isArray(document.metadata.tags)
                  ? document.metadata.tags
                  : [document.metadata.tags]
                ).map((tag, index) => (
                  <Text key={index} figureSmallLabel text03>
                    {tag}
                  </Text>
                ))}
              {document.updated_at &&
                !isNaN(new Date(document.updated_at).getTime()) && (
                  <Text secondaryBody text02>
                    {formatRelativeTime(document.updated_at)}
                  </Text>
                )}
            </Section>

            {/* Blurb */}
            <Text secondaryBody text03 className="text-left">
              {buildDocumentSummaryDisplay(
                document.match_highlights,
                document.blurb
              ) || document.blurb}
            </Text>
          </Section>
        </div>
      </Section>
    </Hoverable>
  );
}
