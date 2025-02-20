import React, { useState, useEffect } from "react";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ResultIcon, SeeMoreBlock } from "@/components/chat/sources/SourceCard";
import { openDocument } from "@/lib/search/utils";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";
import { ValidSources } from "@/lib/types";

interface SourcesDisplayProps {
  documents: OnyxDocument[];
  toggleDocumentSelection: () => void;
  animateEntrance?: boolean;
  threeCols?: boolean;
  hideDocumentDisplay?: boolean;
  docSidebarToggled?: boolean;
  setPresentingDocument: (document: OnyxDocument) => void;
}

export const SourceCard: React.FC<{
  document: OnyxDocument;
  hideDocumentDisplay?: boolean;
  setPresentingDocument: (document: OnyxDocument) => void;
}> = ({ document, hideDocumentDisplay = false, setPresentingDocument }) => {
  const truncatedtext = document.match_highlights[0]
    ? document.match_highlights[0].slice(0, 80)
    : document.blurb?.slice(0, 80) || "";
  const truncatedIdentifier = document.semantic_identifier?.slice(0, 30) || "";
  const documentSummary = hideDocumentDisplay
    ? document.blurb
    : buildDocumentSummaryDisplay(document.match_highlights, document.blurb);

  return (
    <button
      onClick={() =>
        openDocument(document, () => setPresentingDocument(document))
      }
      className="w-full max-w-[260px] h-[80px] p-3
             text-left bg-accent-background hover:bg-accent-background-hovered dark:bg-accent-background-hovered dark:hover:bg-neutral-700/80
             cursor-pointer rounded-lg
             flex flex-col justify-between
             overflow-hidden"
    >
      <div
        className="
        text-text-900 text-xs
        font-medium leading-tight
        whitespace-normal
        break-all
        line-clamp-2
        overflow-hidden
    "
      >
        {documentSummary}
      </div>

      <div className="flex items-center gap-1 mt-1">
        <ResultIcon doc={document} size={18} />
        <div className="text-text-700 text-xs leading-tight truncate flex-1 min-w-0">
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
  setPresentingDocument,
  docSidebarToggled = false,
}) => {
  const displayedDocuments = documents.slice(0, 5);
  const hasMoreDocuments = documents.length > 3;

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
            className={`transition-opacity duration-300 ${
              animateEntrance ? "opacity-100" : "opacity-100"
            }`}
          >
            <SourceCard
              setPresentingDocument={setPresentingDocument}
              hideDocumentDisplay={hideDocumentDisplay}
              document={doc}
            />
          </div>
        ))}
        {hasMoreDocuments && (
          <SeeMoreBlock
            fullWidth
            toggled={docSidebarToggled}
            toggleDocumentSelection={toggleDocumentSelection}
            docs={documents}
            webSourceDomains={documents.map((doc) => doc.link)}
          />
        )}
      </div>
    </div>
  );
};
