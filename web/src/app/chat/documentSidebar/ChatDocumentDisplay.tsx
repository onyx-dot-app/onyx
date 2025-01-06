import { SourceIcon } from "@/components/SourceIcon";
import { OnyxDocument } from "@/lib/search/interfaces";
import { FiTag } from "react-icons/fi";
import { DocumentSelector } from "./DocumentSelector";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";
import { DocumentUpdatedAtBadge } from "@/components/search/DocumentUpdatedAtBadge";
import { MetadataBadge } from "@/components/MetadataBadge";
import { WebResultIcon } from "@/components/WebResultIcon";
import { Dispatch, SetStateAction } from "react";
import { openDocument } from "@/lib/search/utils";

interface DocumentDisplayProps {
  closeSidebar: () => void;
  document: OnyxDocument;
  modal?: boolean;
  isSelected: boolean;
  handleSelect: (documentId: string) => void;
  tokenLimitReached: boolean;
  hideSelection?: boolean;
  setPresentingDocument: Dispatch<SetStateAction<OnyxDocument | null>>;
}

export function DocumentMetadataBlock({
  modal,
  document,
}: {
  modal?: boolean;
  document: OnyxDocument;
}) {
  const MAX_METADATA_ITEMS = 3;
  const metadataEntries = Object.entries(document.metadata);

  return (
    <div className="flex items-center overflow-hidden">
      {document.updated_at && (
        <DocumentUpdatedAtBadge updatedAt={document.updated_at} modal={modal} />
      )}

      {metadataEntries.length > 0 && (
        <>
          <div className="mx-1 h-4 border-l border-border" />
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
              <span className="ml-1 text-xs text-gray-500">...</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function ChatDocumentDisplay({
  closeSidebar,
  document,
  modal,
  hideSelection,
  isSelected,
  handleSelect,
  tokenLimitReached,
  setPresentingDocument,
}: DocumentDisplayProps) {
  const isInternet = document.is_internet;

  if (document.score === null) {
    return null;
  }

  const hasMetadata =
    document.updated_at || Object.keys(document.metadata).length > 0;
  return (
    <div
      className={`max-w-[400px] opacity-100 ${modal ? "w-[90vw]" : "w-full"}`}
    >
      <div
        className={`flex relative flex-col gap-0.5  rounded-xl mx-2 my-1 ${
          isSelected ? "bg-gray-200" : "hover:bg-background-125"
        }`}
      >
        <button
          onClick={() => openDocument(document, setPresentingDocument)}
          className="cursor-pointer text-left flex flex-col px-2 py-1.5"
        >
          <div className="line-clamp-1 mb-1 flex h-6 items-center gap-2 text-xs">
            {document.is_internet || document.source_type === "web" ? (
              <WebResultIcon url={document.link} />
            ) : (
              <SourceIcon sourceType={document.source_type} iconSize={18} />
            )}
            <div className="line-clamp-1 text-text-900 text-sm font-semibold">
              {(document.semantic_identifier || document.document_id).length >
              (modal ? 30 : 40)
                ? `${(document.semantic_identifier || document.document_id)
                    .slice(0, modal ? 30 : 40)
                    .trim()}...`
                : document.semantic_identifier || document.document_id}
            </div>
          </div>
          {hasMetadata && (
            <DocumentMetadataBlock modal={modal} document={document} />
          )}
          <div
            className={`line-clamp-3 text-sm font-normal leading-snug text-gray-600 ${
              hasMetadata ? "mt-2" : ""
            }`}
          >
            {buildDocumentSummaryDisplay(
              document.match_highlights,
              document.blurb
            )}
          </div>
          <div className="absolute top-2 right-2">
            {!isInternet && !hideSelection && (
              <DocumentSelector
                isSelected={isSelected}
                handleSelect={() => handleSelect(document.document_id)}
                isDisabled={tokenLimitReached && !isSelected}
              />
            )}
          </div>
        </button>
      </div>
    </div>
  );
}
