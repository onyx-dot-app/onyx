import { SourceIcon } from "@/components/SourceIcon";
import { MinimalOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import { FiTag } from "react-icons/fi";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";
import { DocumentUpdatedAtBadge } from "@/components/search/DocumentUpdatedAtBadge";
import { MetadataBadge } from "@/components/MetadataBadge";
import { WebResultIcon } from "@/components/WebResultIcon";
import { Dispatch, SetStateAction, useMemo } from "react";
import { openDocument } from "@/lib/search/utils";
import { ValidSources } from "@/lib/types";
import { cn } from "@/lib/utils";
import Truncated from "@/refresh-components/texts/Truncated";
import Text from "@/refresh-components/texts/Text";

interface DocumentMetadataBlockProps {
  modal?: boolean;
  document: OnyxDocument;
}

function DocumentMetadataBlock({
  modal,
  document,
}: DocumentMetadataBlockProps) {
  const MAX_METADATA_ITEMS = 3;
  const metadataEntries = Object.entries(document.metadata);

  return (
    <div className="flex items-center overflow-hidden">
      {document.updated_at && (
        <DocumentUpdatedAtBadge updatedAt={document.updated_at} modal={modal} />
      )}

      {metadataEntries.length > 0 && (
        <>
          <div className="flex items-center overflow-hidden">
            {metadataEntries
              .slice(0, MAX_METADATA_ITEMS)
              .map(([key, value], index) => (
                <MetadataBadge
                  key={index}
                  icon={FiTag}
                  value={`${key}=${value}`}
                />
              ))}
            {metadataEntries.length > MAX_METADATA_ITEMS && (
              <span className="ml-1 text-xs text-text-500">...</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export interface ChatDocumentDisplayProps {
  document: OnyxDocument;
  modal?: boolean;
  isSelected: boolean;
  setPresentingDocument: Dispatch<SetStateAction<MinimalOnyxDocument | null>>;
}

export default function ChatDocumentDisplay({
  document,
  modal,
  isSelected,
  setPresentingDocument,
}: ChatDocumentDisplayProps) {
  const isInternet = document.is_internet;
  const title = useMemo(
    () => document.semantic_identifier || document.document_id,
    [document.semantic_identifier, document.document_id]
  );

  if (document.score === null) {
    return null;
  }

  const hasMetadata =
    document.updated_at || Object.keys(document.metadata).length > 0;

  return (
    <div
      onClick={() => openDocument(document, setPresentingDocument)}
      className={cn(
        "flex w-full flex-col p-3 gap-2 rounded-12 hover:bg-background-tint-00 cursor-pointer",
        isSelected && "bg-action-link-02"
      )}
    >
      <div className="flex items-center gap-2">
        {document.is_internet || document.source_type === ValidSources.Web ? (
          <WebResultIcon url={document.link} />
        ) : (
          <SourceIcon sourceType={document.source_type} iconSize={18} />
        )}
        <Truncated className="line-clamp-2" side="left">
          {title}
        </Truncated>
      </div>

      {hasMetadata && (
        <DocumentMetadataBlock modal={modal} document={document} />
      )}

      <Text as="p" className="line-clamp-2 text-left" secondaryBody text03>
        {buildDocumentSummaryDisplay(document.match_highlights, document.blurb)}
      </Text>
    </div>
  );
}
