import React, { useState, useEffect } from "react";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ResultIcon } from "@/components/chat_search/sources/SourceCard";
import { openDocument } from "@/lib/search/utils";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";

interface SourcesDisplayProps {
  documents: OnyxDocument[];
  toggleDocumentSelection: () => void;
  animateEntrance?: boolean;
}

const SourceCard: React.FC<{ document: OnyxDocument }> = ({ document }) => {
  const truncatedtext = document.match_highlights[0]
    ? document.match_highlights[0].slice(0, 80)
    : document.blurb?.slice(0, 80) || "";
  const truncatedIdentifier = document.semantic_identifier?.slice(0, 30) || "";
  const documentSummary = buildDocumentSummaryDisplay(
    document.match_highlights,
    document.blurb
  );

  return (
    <button
      onClick={() => openDocument(document, () => {})}
      className="w-[260px] h-[80px] p-3 bg-[#f1eee8] text-left hover:bg-[#ebe7de] cursor-pointer rounded-lg flex flex-col justify-between"
    >
      <div className="text-black text-xs line-clamp-2 font-medium leading-tight">
        {/* {truncatedtext} */}
        {/* {truncatedtext.length === 80 ? "..." : ""} */}
        {documentSummary}
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
  animateEntrance = false,
}) => {
  const displayedDocuments = documents.slice(0, 5);
  const hasMoreDocuments = documents.length > 3;
  const [visibleCards, setVisibleCards] = useState<number>(0);

  useEffect(() => {
    if (animateEntrance) {
      const timer = setInterval(() => {
        setVisibleCards((prev) => {
          if (prev < displayedDocuments.length) {
            return prev + 1;
          }
          clearInterval(timer);
          return prev;
        });
      }, 140);

      return () => clearInterval(timer);
    } else {
      setVisibleCards(displayedDocuments.length);
    }
  }, [animateEntrance, displayedDocuments.length]);

  return (
    <div className="w-full max-w-[562px] py-4 flex flex-col gap-4">
      <div className="flex items-center px-4">
        <div className="text-black text-base font-medium">Sources</div>
      </div>

      <div className="grid grid-cols-2 gap-4 px-4">
        {displayedDocuments.map((doc, index) => (
          <div
            key={index}
            onClick={() => openDocument(doc, () => {})}
            className={`transition-opacity duration-300 ${
              index < visibleCards ? "opacity-100" : "opacity-0"
            }`}
          >
            <SourceCard document={doc} />
          </div>
        ))}

        {hasMoreDocuments && (
          <button
            onClick={toggleDocumentSelection}
            className={`w-[260px] h-[80px] p-3 bg-[#f1eee8] hover:bg-[#ebe7de] cursor-pointer rounded-lg flex flex-col items-start justify-between transition-opacity duration-300 ${
              visibleCards === displayedDocuments.length
                ? "opacity-100"
                : "opacity-0"
            }`}
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
