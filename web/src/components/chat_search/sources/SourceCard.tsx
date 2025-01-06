import { WebResultIcon } from "@/components/WebResultIcon";
import { SourceIcon } from "@/components/SourceIcon";
import { OnyxDocument } from "@/lib/search/interfaces";
import { truncateString } from "@/lib/utils";
import { openDocument } from "@/lib/search/utils";

export default function SourceCard({
  doc,
  setPresentingDocument,
}: {
  doc: OnyxDocument;
  setPresentingDocument?: (document: OnyxDocument) => void;
}) {
  return (
    <div
      key={doc.document_id}
      onClick={() => openDocument(doc, setPresentingDocument)}
      className="cursor-pointer text-left overflow-hidden flex flex-col gap-0.5 rounded-sm px-3 py-2.5 hover:bg-background-125 bg-background-100 w-[200px]"
    >
      <div className="line-clamp-1 font-semibold text-ellipsis  text-text-900  flex h-6 items-center gap-2 text-sm">
        {doc.is_internet || doc.source_type === "web" ? (
          <WebResultIcon url={doc.link} />
        ) : (
          <SourceIcon sourceType={doc.source_type} iconSize={18} />
        )}
        <p>{truncateString(doc.semantic_identifier || doc.document_id, 12)}</p>
      </div>
      <div className="line-clamp-2 text-sm font-semibold"></div>
      <div className="line-clamp-2 text-sm font-normal leading-snug text-text-700">
        {doc.blurb}
      </div>
    </div>
  );
}

interface SeeMoreBlockProps {
  documentSelectionToggled: boolean;
  toggleDocumentSelection?: () => void;
  uniqueSources: OnyxDocument["source_type"][];
}

export function SeeMoreBlock({
  documentSelectionToggled,
  toggleDocumentSelection,
  uniqueSources,
}: SeeMoreBlockProps) {
  return (
    <div
      onClick={toggleDocumentSelection}
      className={`
        ${documentSelectionToggled ? "border-border-100 border" : ""}
        cursor-pointer rounded-sm flex-none transition-all duration-500 hover:bg-background-125 bg-text-100 px-3 py-2.5
      `}
    >
      <div className="flex h-6 items-center text-sm">
        <p className="flex-1 mr-1 font-semibold text-text-900 overflow-hidden text-ellipsis whitespace-nowrap">
          {documentSelectionToggled ? "Hide sources" : "See context"}
        </p>
        <div className="flex-shrink-0 flex items-center">
          {uniqueSources.slice(0, 3).map((sourceType, ind) => (
            <div key={ind} className="inline-block ml-1">
              <SourceIcon sourceType={sourceType} iconSize={16} />
            </div>
          ))}
          {uniqueSources.length > 3 && (
            <span className="text-xs text-text-700 font-semibold ml-1">
              +{uniqueSources.length - 3}
            </span>
          )}
        </div>
      </div>
      <div className="line-clamp-2 text-sm font-normal leading-snug text-text-700 mt-1">
        See more
      </div>
    </div>
  );
}
