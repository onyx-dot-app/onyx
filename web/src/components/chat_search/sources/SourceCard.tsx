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
      className="cursor-pointer h-[80px] text-left overflow-hidden flex flex-col gap-0.5 rounded-lg px-3 py-2 bg-[#f1eee8] hover:bg-[#ebe7de] w-[200px]"
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
  // Gather total sources (unique + web).
  const totalSources = uniqueSources.length + webSourceDomains.length;

  // Filter out "web" from unique sources if we have any webSourceDomains
  // (preserves the original logic).
  const filteredUniqueSources = uniqueSources.filter(
    (source) => source !== "web" && webSourceDomains.length > 0
  );

  // Build a list of up to three icons from the filtered unique sources and web sources.
  // If we don't reach three icons but have at least one, we'll duplicate the last one.
  const iconsToRender: Array<{ type: "source" | "web"; data: string }> = [];

  // Push from filtered unique sources (max 3).
  for (
    let i = 0;
    i < filteredUniqueSources.length && iconsToRender.length < 3;
    i++
  ) {
    iconsToRender.push({ type: "source", data: filteredUniqueSources[i] });
  }

  // Then push from web source domains (until total of 3).
  for (
    let i = 0;
    i < webSourceDomains.length && iconsToRender.length < 3;
    i++
  ) {
    iconsToRender.push({ type: "web", data: webSourceDomains[i] });
  }

  // If we have fewer than 3 but at least one icon, duplicate the last until we reach 3.
  while (iconsToRender.length < 3 && iconsToRender.length > 0) {
    iconsToRender.push(iconsToRender[iconsToRender.length - 1]);
  }

  return (
    <button
      onClick={toggleDocumentSelection}
      className="w-full max-w-[260px] h-[80px] p-3 bg-[#f1eee8] text-left hover:bg-[#ebe7de] cursor-pointer rounded-lg flex flex-col justify-between overflow-hidden"
    >
      <div className="flex items-center gap-1">
        {iconsToRender.map((icon, index) =>
          icon.type === "source" ? (
            <SourceIcon
              key={index}
              sourceType={icon.data as ValidSources}
              iconSize={14}
            />
          ) : (
            <WebResultIcon key={index} url={icon.data} size={14} />
          )
        )}
      </div>
      <div className="text-text-darker text-xs font-semibold">
        {toggled ? "Hide Results" : "Show All"}
      </div>
    </button>
  );
}
