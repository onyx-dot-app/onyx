import React from "react";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ResultIcon, SeeMoreBlock } from "@/components/chat/sources/SourceCard";
import { openDocument } from "@/lib/search/utils";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";
import { getFileIconFromFileNameAndLink } from "@/lib/assistantIconUtils";
import { truncateString } from "@/lib/utils";
import { FileResponse } from "../my-documents/DocumentsContext";

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

export const FileSourceCard: React.FC<{
  document: FileResponse;
  setPresentingDocument: (document: FileResponse) => void;
  relevantDocument: OnyxDocument | undefined;
}> = ({ document, setPresentingDocument, relevantDocument }) => {
  const openDocument = () => {
    if (document.link_url) {
      window.open(document.link_url, "_blank");
    } else {
      setPresentingDocument(document as any);
    }
  };
  const fileName = document.name || document.id;

  return (
    <button
      onClick={openDocument}
      className="w-full max-w-[260px] h-[80px] p-3
             text-left bg-accent-background hover:bg-accent-background-hovered dark:bg-accent-background-hovered dark:hover:bg-neutral-700/80
             cursor-pointer rounded-lg
             flex flex-col justify-between"
    >
      <div
        className="
        text-text-900 text-xs
        font-medium leading-tight
        whitespace-normal
        break-all
        line-clamp-2 
        text-ellipsis
      "
      >
        {relevantDocument
          ? buildDocumentSummaryDisplay(
              relevantDocument?.match_highlights || [],
              relevantDocument?.blurb || ""
            )
          : "This file has not been indexed yet"}
      </div>

      <div className="flex items-center gap-1 mt-1">
        {getFileIconFromFileNameAndLink(document.name, document.link_url)}
        <div className="text-text-700 text-xs leading-tight truncate flex-1 min-w-0">
          {truncateString(document.name, 45)}
        </div>
      </div>
    </button>
  );
};

export const FileSourceCardInResults: React.FC<{
  document: FileResponse;
  setPresentingDocument: (document: FileResponse) => void;
  relevantDocument: OnyxDocument | undefined;
}> = ({ document, setPresentingDocument, relevantDocument }) => {
  const openDocument = () => {
    if (document.link_url) {
      window.open(document.link_url, "_blank");
    } else {
      setPresentingDocument(document as any);
    }
  };
  return (
    <button
      onClick={openDocument}
      className="w-full rounded-xl 
             text-left bg-background hover:bg-neutral-100 dark:bg-neutral-800 dark:hover:bg-neutral-700
             cursor-pointer
             flex flex-col 
             border border-neutral-200 dark:border-neutral-700
             px-3 py-2.5 my-1"
    >
      <div className="flex items-center gap-2 mb-1">
        <div className="flex-shrink-0">
          {getFileIconFromFileNameAndLink(document.name, document.link_url)}
        </div>
        <div className="text-neutral-900 dark:text-neutral-300 text-sm font-semibold truncate flex-1 min-w-0">
          {truncateString(document.name, 45)}
        </div>
      </div>

      <div
        className="
        text-neutral-900 dark:text-neutral-300 text-sm
        font-normal leading-snug
        whitespace-normal
        break-all
        line-clamp-3
        overflow-hidden
        mt-2
      "
      >
        {buildDocumentSummaryDisplay(
          relevantDocument?.match_highlights || [],
          relevantDocument?.blurb || ""
        )}
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
