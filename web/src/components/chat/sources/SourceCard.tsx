import { WebResultIcon } from "@/components/WebResultIcon";
import { SourceIcon } from "@/components/SourceIcon";
import { OnyxDocument } from "@/lib/search/interfaces";
import { truncateString } from "@/lib/utils";
import { openDocument } from "@/lib/search/utils";
import { ValidSources } from "@/lib/types";
import React from "react";
import { SearchResultIcon } from "@/components/SearchResultIcon";

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

// export default function SourceCard({
//   doc,
//   setPresentingDocument,
// }: {
//   doc: OnyxDocument;
//   setPresentingDocument?: (document: OnyxDocument) => void;
// }) {
//   return (
//     <div
//       key={doc.document_id}
//       onClick={() => openDocument(doc, setPresentingDocument)}
//       className="cursor-pointer h-[80px] text-left overflow-hidden flex flex-col gap-0.5 rounded-lg px-3 py-2 bg-accent-background hover:bg-accent-background-hovered w-[200px]"
//     >
//       <div className="line-clamp-1 font-semibold text-ellipsis text-text-900  flex h-6 items-center gap-2 text-sm">
//         {doc.is_internet || doc.source_type === "web" ? (
//           <WebResultIcon url={doc.link} />
//         ) : (
//           <SourceIcon sourceType={doc.source_type} iconSize={18} />
//         )}
//         <p>{truncateString(doc.semantic_identifier || doc.document_id, 20)}</p>
//       </div>
//       <div className="line-clamp-2 text-sm font-semibold"></div>
//       <div className="line-clamp-2 text-sm font-normal leading-snug text-text-700">
//         {doc.blurb}
//       </div>
//     </div>
//   );
// }

interface SeeMoreBlockProps {
  toggleDocumentSelection: () => void;
  docs: OnyxDocument[];
  webSourceDomains: string[];
  toggled: boolean;
  fullWidth?: boolean;
}

const getDomainFromUrl = (url: string) => {
  try {
    const parsedUrl = new URL(url);
    return parsedUrl.hostname;
  } catch (error) {
    return null;
  }
};
export function getUniqueIcons(docs: OnyxDocument[]): JSX.Element[] {
  const uniqueIcons: JSX.Element[] = [];
  const seenDomains = new Set<string>();
  const seenSourceTypes = new Set<ValidSources>();

  for (const doc of docs) {
    // If it's a web source, we check domain uniqueness
    if ((doc.is_internet || doc.source_type === ValidSources.Web) && doc.link) {
      const domain = getDomainFromUrl(doc.link);
      if (domain && !seenDomains.has(domain)) {
        seenDomains.add(domain);
        // Use your SearchResultIcon with the doc.url
        uniqueIcons.push(
          <SearchResultIcon url={doc.link} key={`web-${doc.document_id}`} />
        );
      }
    } else {
      // Otherwise, use sourceType uniqueness
      if (!seenSourceTypes.has(doc.source_type)) {
        seenSourceTypes.add(doc.source_type);
        // Use your SourceIcon with the doc.sourceType
        uniqueIcons.push(
          <SourceIcon
            sourceType={doc.source_type}
            iconSize={18}
            key={doc.document_id}
          />
        );
      }
    }
  }

  // If we have zero icons, we might want a fallback (optional):
  if (uniqueIcons.length === 0) {
    // Fallback: just use a single SourceIcon, repeated 3 times
    return [
      <SourceIcon
        sourceType={ValidSources.Web}
        iconSize={18}
        key="fallback-1"
      />,
      <SourceIcon
        sourceType={ValidSources.Web}
        iconSize={18}
        key="fallback-2"
      />,
      <SourceIcon
        sourceType={ValidSources.Web}
        iconSize={18}
        key="fallback-3"
      />,
    ];
  }

  // Duplicate last icon if fewer than 3 icons
  while (uniqueIcons.length < 3) {
    // The last icon in the array
    const lastIcon = uniqueIcons[uniqueIcons.length - 1];
    // Clone it with a new key
    uniqueIcons.push(
      React.cloneElement(lastIcon, {
        key: `${lastIcon.key}-dup-${uniqueIcons.length}`,
      })
    );
  }

  // Slice to just the first 3 if there are more than 3
  return uniqueIcons.slice(0, 3);
}

export function SeeMoreBlock({
  toggleDocumentSelection,
  webSourceDomains,
  docs,
  toggled,
  fullWidth = false,
}: SeeMoreBlockProps) {
  const iconsToRender = docs.length > 2 ? getUniqueIcons(docs) : [];

  return (
    <button
      onClick={toggleDocumentSelection}
      className={`w-full ${fullWidth ? "w-full" : "max-w-[200px]"}
        h-[80px] p-3 border border-[1.5px] border-new-background-light   text-left bg-accent-background hover:bg-accent-background-hovered dark:bg-accent-background-hovered dark:hover:bg-neutral-700/80 cursor-pointer rounded-lg flex flex-col justify-between overflow-hidden`}
    >
      <div className="flex items-center gap-1">
        {docs.length > 2 && iconsToRender.map((icon, index) => icon)}
      </div>
      <div className="text-text-darker text-xs font-semibold">
        {toggled ? "Hide Results" : "Show All"}
      </div>
    </button>
  );
}
