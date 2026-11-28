"use client";

import { Section } from "@opal/layouts";
import { Badge, Text } from "@opal/components";
import { SearchDocWithContent } from "@/lib/search/types";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";
import { ValidSources } from "@/lib/connectors/types/source";
import { MinimalOnyxDocument } from "@/lib/search/types";
import { Interactive } from "@opal/core";
import { richNodes } from "@opal/utils";
import { timeAgo } from "@opal/time";
import { useMemo } from "react";
import { useLocale } from "next-intl";

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
  const locale = useLocale();
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
    <Interactive.Stateless onClick={handleClick} prominence="secondary">
      <Interactive.Container size="fit" width="full">
        <Section alignItems="start" gap={0} padding={1}>
          {/* Title Row */}
          <Section
            flexDirection="row"
            justifyContent="start"
            gap={1}
            padding={1}
          >
            {isWebSource && document.link ? (
              <WebResultIcon url={document.link} size={18} />
            ) : (
              <SourceIcon sourceType={document.source_type} iconSize={16} />
            )}

            <Text
              maxLines={1}
              overflowTooltip
              as="p"
              textPosition="text-start"
              font="main-ui-action"
              color="text-05"
            >
              {document.semantic_identifier}
            </Text>
          </Section>

          {/* Body Row */}
          <div className="px-1 pb-1">
            <Section alignItems="start" gap={1}>
              {/* Metadata */}
              <Section flexDirection="row" justifyContent="start" gap={1}>
                {(document.primary_owners ?? []).map((owner, index) => (
                  <Badge key={index} title={owner} />
                ))}
                {document.metadata?.tags &&
                  (Array.isArray(document.metadata.tags)
                    ? document.metadata.tags
                    : [document.metadata.tags]
                  ).map((tag, index) => <Badge key={index} title={tag} />)}
                {document.updated_at &&
                  !isNaN(new Date(document.updated_at).getTime()) && (
                    <Text font="secondary-body" color="text-02">
                      {timeAgo(document.updated_at, locale) ?? ""}
                    </Text>
                  )}
              </Section>

              {/* Blurb */}
              {content && (
                <Text font="secondary-body" color="text-03">
                  {richNodes(content)}
                </Text>
              )}
            </Section>
          </div>
        </Section>
      </Interactive.Container>
    </Interactive.Stateless>
  );
}
