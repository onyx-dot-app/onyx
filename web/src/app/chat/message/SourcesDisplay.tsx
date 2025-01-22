import React, { useState, useEffect } from "react";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ResultIcon } from "@/components/chat_search/sources/SourceCard";
import { openDocument } from "@/lib/search/utils";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";

interface SourcesDisplayProps {
  documents: OnyxDocument[];
  toggleDocumentSelection: () => void;
  animateEntrance?: boolean;
  threeCols?: boolean;
  hideDocumentDisplay?: boolean;
}

const SourceCard: React.FC<{
  document: OnyxDocument;
  hideDocumentDisplay?: boolean;
}> = ({ document, hideDocumentDisplay = false }) => {
  const truncatedtext = document.match_highlights[0]
    ? document.match_highlights[0].slice(0, 80)
    : document.blurb?.slice(0, 80) || "";
  const truncatedIdentifier = document.semantic_identifier?.slice(0, 30) || "";
  const documentSummary = hideDocumentDisplay
    ? document.blurb
    : buildDocumentSummaryDisplay(document.match_highlights, document.blurb);

  return (
    <button
      onClick={() => openDocument(document, () => {})}
      className="max-w-[260px] h-[80px] p-3 bg-[#f1eee8] text-left hover:bg-[#ebe7de] cursor-pointer rounded-lg flex flex-col justify-between"
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
  threeCols = false,
  hideDocumentDisplay = false,
}) => {
  const displayedDocuments = documents.slice(0, 5);
  const hasMoreDocuments = documents.length > 3;
  // const [visibleCards, setVisibleCards] = useState<number>(0);

  // useEffect(() => {
  //   if (animateEntrance) {
  //     const timer = setInterval(() => {
  //       setVisibleCards((prev) => {
  //         if (prev < displayedDocuments.length) {
  //           return prev + 1;
  //         }
  //         clearInterval(timer);
  //         return prev;
  //       });
  //     }, 140);

  //     return () => clearInterval(timer);
  //   } else {
  //     setVisibleCards(displayedDocuments.length);
  //   }
  // }, [animateEntrance, displayedDocuments.length]);

  return (
    <div
      className={`w-full  py-4 flex flex-col gap-4 ${
        threeCols ? "" : "max-w-[562px]"
      }`}
    >
      <div className="flex items-center px-4">
        <div className="text-black text-lg font-medium">Sources</div>
      </div>
      <div
        className={`grid  w-full ${
          threeCols ? "grid-cols-3" : "grid-cols-2"
        } gap-4 px-4`}
      >
        {displayedDocuments.map((doc, index) => (
          <div
            key={index}
            onClick={() => openDocument(doc, () => {})}
            className={`transition-opacity duration-300 ${
              animateEntrance ? "opacity-100" : "opacity-100"
            }`}
          >
            <SourceCard
              hideDocumentDisplay={hideDocumentDisplay}
              document={doc}
            />
          </div>
        ))}

        {hasMoreDocuments && (
          <button
            onClick={toggleDocumentSelection}
            className={`max-w-[260px] h-[80px] p-3 bg-[#f1eee8] hover:bg-[#ebe7de] cursor-pointer rounded-lg flex flex-col items-start justify-between transition-opacity duration-300 ${
              animateEntrance ? "opacity-100" : "opacity-100"
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
