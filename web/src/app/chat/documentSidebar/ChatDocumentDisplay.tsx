import { HoverPopup } from "@/components/HoverPopup";
import { SourceIcon } from "@/components/SourceIcon";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { DanswerDocument } from "@/lib/search/interfaces";
import { FiInfo, FiRadio, FiTag } from "react-icons/fi";
import { DocumentSelector } from "./DocumentSelector";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";
import { InternetSearchIcon } from "@/components/InternetSearchIcon";
import { DocumentUpdatedAtBadge } from "@/components/search/DocumentUpdatedAtBadge";
import { MetadataBadge } from "@/components/MetadataBadge";

interface DocumentDisplayProps {
  document: DanswerDocument;
  queryEventId: number | null;
  isAIPick: boolean;
  isSelected: boolean;
  handleSelect: (documentId: string) => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  tokenLimitReached: boolean;
}

export function DocumentMetadataBlock({
  document,
}: {
  document: DanswerDocument;
}) {
  const MAX_METADATA_ITEMS = 3;
  // const metadataEntries = Object.entries(document.metadata);
  const metadataEntriesCopy1 = Object.entries(document.metadata || ["l"]);
  const metadataEntriesCopy2 = Object.entries(document.metadata || ["l"]);
  const metadataEntriesCopy3 = Object.entries(document.metadata || ["l"]);
  const metadataEntriesCopy4 = Object.entries(document.metadata || ["l"]);
  const metadataEntries = [
    ...metadataEntriesCopy1,
    ...metadataEntriesCopy2,
    ...metadataEntriesCopy3,
    ...metadataEntriesCopy4,
  ];

  return (
    <div className="flex items-center overflow-hidden">
      {document.updated_at && (
        <DocumentUpdatedAtBadge updatedAt={document.updated_at} />
      )}

      {metadataEntries.length > 0 && (
        <>
          <div className="mx-1 h-4 border-l border-border" />
          <div className="flex items-center overflow-hidden">
            {metadataEntries
              .slice(0, MAX_METADATA_ITEMS)
              .map(([key, value], index) => (
                <MetadataBadge icon={FiTag} value={`${key}=${value}`} />
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
  document,
  queryEventId,
  isAIPick,
  isSelected,
  handleSelect,
  setPopup,
  tokenLimitReached,
}: DocumentDisplayProps) {
  const isInternet = document.is_internet;

  if (document.score === null) {
    return null;
  }

  const faviconUrl =
    isInternet && document.link
      ? `https://www.google.com/s2/favicons?domain=${
          new URL(document.link).hostname
        }&sz=32`
      : null;
  const source = document.link
    ? (() => {
        try {
          return new URL(document.link).hostname;
        } catch {
          return document.link;
        }
      })()
    : document.source_type;

  return (
    <div className="opacity-100 will-change-auto">
      <div
        className={`flex relative flex-col gap-0.5  rounded-xl mx-2 my-1.5 ${
          isSelected ? "bg-gray-200" : "hover:bg-background-125"
        }`}
      >
        <a
          href={document.link}
          target="_blank"
          rel="noopener noreferrer"
          className="cursor-pointer flex flex-col px-2 py-1.5"
        >
          <div className="line-clamp-1 mb-1 flex h-6 items-center gap-2 text-xs">
            {faviconUrl ? (
              <img
                alt="Favicon"
                width="32"
                height="32"
                className="rounded-full bg-gray-200 object-cover"
                src={faviconUrl}
              />
            ) : (
              <SourceIcon sourceType={document.source_type} iconSize={18} />
            )}
            <div className="line-clamp-1 text-text-900 text-sm font-semibold">
              {document.semantic_identifier || document.document_id}
            </div>
          </div>
          <DocumentMetadataBlock document={document} />
          <div className="line-clamp-2 pt-2 text-sm font-normal leading-snug text-gray-600">
            {buildDocumentSummaryDisplay(
              document.match_highlights,
              document.blurb
            )}
          </div>
          <div className="absolute top-2 right-2">
            {!isInternet && (
              <DocumentSelector
                isSelected={isSelected}
                handleSelect={() => handleSelect(document.document_id)}
                isDisabled={tokenLimitReached && !isSelected}
              />
            )}
          </div>
        </a>
      </div>
    </div>
  );
}
