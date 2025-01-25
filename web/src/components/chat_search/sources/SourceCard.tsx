import { WebResultIcon } from "@/components/WebResultIcon";
import { SourceIcon } from "@/components/SourceIcon";
import { OnyxDocument } from "@/lib/search/interfaces";
import { truncateString } from "@/lib/utils";
import { openDocument } from "@/lib/search/utils";
import { ValidSources } from "@/lib/types";

export const ResultIcon = ({
  doc,
  size,
}: {
  doc: OnyxDocument;
  size: number;
}) => {
  return (
    <div className="flex-none">
      {" "}
      {doc.is_internet || doc.source_type === "web" ? (
        <WebResultIcon size={size} url={doc.link} />
      ) : (
        <SourceIcon iconSize={size} sourceType={doc.source_type} />
      )}
    </div>
  );
};

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
      className="cursor-pointer text-left overflow-hidden flex flex-col gap-0.5 rounded-lg px-3 py-2 hover:bg-background-dark/80 bg-background-dark/60 w-[200px]"
    >
      <div className="line-clamp-1 font-semibold text-ellipsis text-text-900  flex h-6 items-center gap-2 text-sm">
        {doc.is_internet || doc.source_type === "web" ? (
          <WebResultIcon url={doc.link} />
        ) : (
          <SourceIcon sourceType={doc.source_type} iconSize={18} />
        )}
        <p>{truncateString(doc.semantic_identifier || doc.document_id, 20)}</p>
      </div>
      <div className="line-clamp-2 text-sm font-semibold"></div>
      <div className="line-clamp-2 text-sm font-normal leading-snug text-text-700">
        {doc.blurb}
      </div>
    </div>
  );
}

interface SeeMoreBlockProps {
  toggleDocumentSelection: () => void;
  uniqueSources: ValidSources[];
  webSourceDomains: string[];
  toggled: boolean;
}

export function SeeMoreBlock({
  toggleDocumentSelection,
  webSourceDomains,
  uniqueSources,
  toggled,
}: SeeMoreBlockProps) {
  const filteredUniqueSources = uniqueSources.filter(
    (source) => source !== "web" && webSourceDomains.length > 0
  );
  const numOfWebSourcesToDisplay = 3 - filteredUniqueSources.length;
  return (
    <button
      onClick={toggleDocumentSelection}
      className={`max-w-[260px] min-w-[100px] h-[80px] p-3 bg-[#f1eee8] hover:bg-[#ebe7de] cursor-pointer rounded-lg flex flex-col items-start justify-between transition-opacity duration-300`}
    >
      <div className="flex items-center gap-1">
        {filteredUniqueSources.slice(0, 3).map((source, index) => (
          <SourceIcon key={index} sourceType={source} iconSize={14} />
        ))}
        {webSourceDomains
          .slice(0, numOfWebSourcesToDisplay)
          .map((domain, index) => (
            <WebResultIcon key={index} url={domain} size={14} />
          ))}
        {uniqueSources.length > 3 && (
          <span className="text-xs text-[#4a4a4a] font-medium ml-1">
            +{uniqueSources.length - 3}
          </span>
        )}
      </div>

      <div className="text-text-darker text-xs font-semibold">
        {toggled ? "Hide Results" : "Show All"}
      </div>
    </button>
  );
}
