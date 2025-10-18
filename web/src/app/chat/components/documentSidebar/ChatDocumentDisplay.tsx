import { SourceIcon } from "@/components/SourceIcon";
import { MinimalOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import { FiTag } from "react-icons/fi";
import DocumentSelector from "./DocumentSelector";
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

interface DocumentDisplayProps {
  closeSidebar: () => void;
  document: OnyxDocument;
  modal?: boolean;
  isSelected: boolean;
  handleSelect: (documentId: string) => void;
  tokenLimitReached: boolean;
  hideSelection?: boolean;
  setPresentingDocument: Dispatch<SetStateAction<MinimalOnyxDocument | null>>;
}

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

export function ChatDocumentDisplay({
  document,
  modal,
  hideSelection,
  isSelected,
  handleSelect,
  tokenLimitReached,
  setPresentingDocument,
}: DocumentDisplayProps) {
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
    <button
      onClick={() => openDocument(document, setPresentingDocument)}
      className={cn(
        "flex w-full flex-col p-padding-button gap-spacing-interline rounded-12 hover:bg-background-tint-00",
        isSelected && "bg-action-link-02"
      )}
    >
      <div className="flex items-center gap-spacing-interline">
        {document.is_internet || document.source_type === ValidSources.Web ? (
          <WebResultIcon url={document.link} />
        ) : (
          <SourceIcon sourceType={document.source_type} iconSize={18} />
        )}
        <Truncated className="line-clamp-2" side="left">
          {title}
        </Truncated>
        {!isInternet && !hideSelection && (
          <DocumentSelector
            isSelected={isSelected}
            handleSelect={() => handleSelect(document.document_id)}
            isDisabled={tokenLimitReached && !isSelected}
          />
        )}
      </div>

      {hasMetadata && (
        <DocumentMetadataBlock modal={modal} document={document} />
      )}

      <Text className="line-clamp-2 text-left" secondaryBody text03>
        {buildDocumentSummaryDisplay(document.match_highlights, document.blurb)}
      </Text>
    </button>
  );
}
