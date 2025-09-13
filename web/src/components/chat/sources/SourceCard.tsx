import { WebResultIcon } from "@/components/WebResultIcon";
import { SourceIcon } from "@/components/SourceIcon";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";
import React, { useEffect, useState } from "react";
import { SearchResultIcon } from "@/components/SearchResultIcon";
import { getFileIconFromFileNameAndLink } from "@/lib/assistantIconUtils";
// Minimal shape needed locally for file icon rendering
type FileResponse = {
  id: number;
  name: string;
  link_url?: string | null;
};

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
    if (lastIcon) {
      // Clone it with a new key
      uniqueIcons.push(
        React.cloneElement(lastIcon, {
          key: `${lastIcon.key}-dup-${uniqueIcons.length}`,
        })
      );
    }
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
        h-[80px] p-3 border border-[1.5px] border-new-background-light text-left bg-accent-background hover:bg-accent-background-hovered dark:bg-accent-background-hovered dark:hover:bg-neutral-700/80 cursor-pointer rounded-lg flex flex-col justify-between overflow-hidden`}
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

export function getUniqueFileIcons(files: FileResponse[]): JSX.Element[] {
  const uniqueIcons: JSX.Element[] = [];
  const seenExtensions = new Set<string>();

  // Helper function to get a styled icon
  const getStyledIcon = (
    fileName: string,
    fileId: number,
    link_url?: string | null
  ) => {
    return React.cloneElement(
      getFileIconFromFileNameAndLink(fileName, link_url),
      {
        key: `file-${fileId}`,
      }
    );
  };

  for (const file of files) {
    uniqueIcons.push(getStyledIcon(file.name, file.id, file.link_url));
  }

  // If we have zero icons, use a fallback
  if (uniqueIcons.length === 0) {
    return [
      getFileIconFromFileNameAndLink("fallback1.txt"),
      getFileIconFromFileNameAndLink("fallback2.txt"),
      getFileIconFromFileNameAndLink("fallback3.txt"),
    ];
  }

  // Duplicate last icon if fewer than 3 icons
  while (uniqueIcons.length < 3) {
    // The last icon in the array
    const lastIcon = uniqueIcons[uniqueIcons.length - 1];
    if (lastIcon) {
      // Clone it with a new key
      uniqueIcons.push(
        React.cloneElement(lastIcon, {
          key: `${lastIcon.key}-dup-${uniqueIcons.length}`,
        })
      );
    }
  }

  // Slice to just the first 3 if there are more than 3
  return uniqueIcons.slice(0, 3);
}

export function FilesSeeMoreBlock({
  toggleDocumentSelection,
  files,
  toggled,
  fullWidth = false,
}: {
  toggleDocumentSelection: () => void;
  files: FileResponse[];
  toggled: boolean;
  fullWidth?: boolean;
}) {
  const [iconsToRender, setIconsToRender] = useState<JSX.Element[]>([]);
  useEffect(() => {
    setIconsToRender(files.length > 2 ? getUniqueFileIcons(files) : []);
  }, [files]);

  return (
    <button
      onClick={toggleDocumentSelection}
      className={`w-full ${fullWidth ? "w-full" : "max-w-[200px]"}
        h-[80px] p-3 border border-[1.5px] border-new-background-light text-left bg-accent-background hover:bg-accent-background-hovered dark:bg-accent-background-hovered dark:hover:bg-neutral-700/80 cursor-pointer rounded-lg flex flex-col justify-between overflow-hidden`}
    >
      <div className="flex items-center gap-1">
        {files.length > 2 && iconsToRender.map((icon, index) => icon)}
      </div>
      <div className="text-text-darker text-xs font-semibold">
        {toggled ? "Hide Files" : "Show All Files"}
      </div>
    </button>
  );
}
