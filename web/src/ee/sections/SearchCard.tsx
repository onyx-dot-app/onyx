"use client";

import { SearchDocWithContent } from "@/lib/search/interfaces";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import Text from "@/refresh-components/texts/Text";
import Chip from "@/refresh-components/Chip";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";
import { ValidSources } from "@/lib/types";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { Section } from "@/layouts/general-layouts";
import { Interactive } from "@opal/core";
import Truncated from "@/refresh-components/texts/Truncated";
import { timeAgo } from "@/lib/time";
import { useMemo } from "react";

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

  function handleClick() {
    if (document.link) {
      window.open(document.link, "_blank", "noopener,noreferrer");
      return;
    }
    onDocumentClick({
      document_id: document.document_id,
      semantic_identifier: document.semantic_identifier,
    });
  }

  const content = useMemo(
    () =>
      buildDocumentSummaryDisplay(document.match_highlights, document.blurb) ||
      document.blurb,
    [document.match_highlights, document.blurb]
  );

  return (
    <Interactive.Base onClick={handleClick} prominence="secondary">
      <Interactive.Container heightVariant="fit">
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
                {(document.primary_owners ?? []).map((owner, index) => (
                  <Chip key={index}>{owner}</Chip>
                ))}
                {document.metadata?.tags &&
                  (Array.isArray(document.metadata.tags)
                    ? document.metadata.tags
                    : [document.metadata.tags]
                  ).map((tag, index) => <Chip key={index}>{tag}</Chip>)}
                {document.updated_at &&
                  !isNaN(new Date(document.updated_at).getTime()) && (
                    <Text secondaryBody text02>
                      {timeAgo(document.updated_at)}
                    </Text>
                  )}
              </Section>

              {/* Blurb */}
              {content && (
                <Text secondaryBody text03 className="text-left">
                  {content}
                </Text>
              )}
            </Section>
          </div>
        </Section>
      </Interactive.Container>
    </Interactive.Base>
  );
}
