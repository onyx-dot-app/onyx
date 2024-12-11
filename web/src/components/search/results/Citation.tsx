import { ReactNode } from "react";
import { CompactDocumentCard } from "../DocumentDisplay";
import { LoadedDanswerDocument } from "@/lib/search/interfaces";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ValidSources } from "@/lib/types";

export function Citation({
  children,
  link,
  document,
  index,
  updatePresentingDocument,
  icon,
  url,
}: {
  link?: string;
  children?: JSX.Element | string | null | ReactNode;
  index?: number;
  updatePresentingDocument: (documentIndex: LoadedDanswerDocument) => void;
  document: LoadedDanswerDocument;
  icon?: React.ReactNode;
  url?: string;
}) {
  const innerText = children
    ? children?.toString().split("[")[1].split("]")[0]
    : index;

  if (link) {
    return (
      <TooltipProvider delayDuration={0}>
        <Tooltip>
          <TooltipTrigger asChild>
            <div
              onMouseDown={() => {
                if (document.source_type == ValidSources.File) {
                  updatePresentingDocument(document);
                } else {
                  window.open(link, "_blank");
                }
              }}
              className="inline-flex items-center ml-1 cursor-pointer transition-all duration-200 ease-in-out"
            >
              <span className="relative min-w-[1.4rem] text-center no-underline -top-0.5 px-1.5 py-0.5 text-xs font-medium text-gray-700 bg-gray-100 rounded-full border border-gray-300 hover:bg-gray-200 hover:text-gray-900 shadow-sm no-underline">
                {innerText}
              </span>
            </div>
          </TooltipTrigger>
          <TooltipContent width="mb-2 max-w-lg" className="bg-background">
            <CompactDocumentCard
              updatePresentingDocument={updatePresentingDocument}
              url={url}
              icon={icon}
              document={document}
            />
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  } else {
    return (
      <TooltipProvider delayDuration={0}>
        <Tooltip>
          <TooltipTrigger asChild>
            <div
              onMouseDown={() => {
                if (document.source_type == ValidSources.File) {
                  updatePresentingDocument(document);
                } else {
                  window.open(document.link, "_blank");
                }
              }}
              className="inline-flex items-center ml-1 cursor-pointer transition-all duration-200 ease-in-out"
            >
              <span className="relative min-w-[1.4rem]  pchatno-underline -top-0.5 px-1.5 py-0.5 text-xs font-medium text-gray-700 bg-gray-100 rounded-full border border-gray-300 hover:bg-gray-200 hover:text-gray-900 shadow-sm no-underline">
                {innerText}
              </span>
            </div>
          </TooltipTrigger>
          <TooltipContent width="mb-2 max-w-lg" backgroundColor="bg-background">
            <CompactDocumentCard
              updatePresentingDocument={updatePresentingDocument}
              url={url}
              icon={icon}
              document={document}
            />
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }
}
