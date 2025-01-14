import React from "react";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ResultIcon } from "@/components/chat_search/sources/SourceCard";
import { openDocument } from "@/lib/search/utils";

interface SourcesDisplayProps {
  documents: OnyxDocument[];
  toggleDocumentSelection: () => void;
}

const SourceCard: React.FC<{ document: OnyxDocument }> = ({ document }) => {
  const truncatedBlurb = document.blurb?.slice(0, 80) || "";
  const truncatedIdentifier = document.semantic_identifier?.slice(0, 30) || "";

  return (
    <button
      onClick={() => openDocument(document, () => {})}
      className="w-[260px] h-[80px] p-3 bg-[#f1eee8] text-left hover:bg-[#ebe7de] cursor-pointer rounded-lg flex flex-col justify-between"
    >
      <div className="text-black text-xs line-clamp-2 font-medium leading-tight">
        {truncatedBlurb}
        {truncatedBlurb.length === 80 ? "..." : ""}
      </div>
      <div className="flex items-center gap-1">
        <ResultIcon doc={document} size={14} />
        <div className="text-[#4a4a4a] text-xs leading-tight truncate">
          {truncatedIdentifier}
        </div>
      </div>
    </button>
  );
};

export const SourcesDisplay: React.FC<SourcesDisplayProps> = ({
  documents,
  toggleDocumentSelection,
}) => {
  const displayedDocuments = documents.slice(0, 3);
  const hasMoreDocuments = documents.length > 3;

  return (
    <div className="w-full max-w-[562px] py-4 flex flex-col gap-4">
      <div className="flex items-center px-4">
        <div className="text-black text-base font-medium font-['KH Teka TRIAL']">
          Sources
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4 px-4">
        {displayedDocuments.map((doc, index) => (
          <div key={index} onClick={() => openDocument(doc, () => {})}>
            <SourceCard document={doc} />
          </div>
        ))}
        {hasMoreDocuments && (
          <button
            onClick={toggleDocumentSelection}
            className="w-[260px] h-[80px] p-3 bg-[#f1eee8] hover:bg-[#ebe7de] cursor-pointer rounded-lg flex  flex-col  items-start justify-between"
          >
            <div className="flex items-center gap-1">
              {documents.slice(3, 6).map((doc, index) => (
                <ResultIcon key={index} doc={doc} size={14} />
              ))}
            </div>
            <div className="text-[#4a4a4a] text-xs font-medium">Show All</div>
          </button>
        )}
      </div>
    </div>
  );
};
