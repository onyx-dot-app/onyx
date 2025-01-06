import { ReactNode } from "react";
import { CompactDocumentCard } from "../DocumentDisplay";
import { LoadedOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ValidSources } from "@/lib/types";
import { openDocument } from "@/lib/search/utils";

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
  updatePresentingDocument: (document: OnyxDocument) => void;
  document: LoadedOnyxDocument;
  icon?: React.ReactNode;
  url?: string;
}) {
  const innerText = children
    ? children?.toString().split("[")[1].split("]")[0]
    : index;

  return (
    <TooltipProvider delayDuration={0}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            onClick={() => openDocument(document, updatePresentingDocument)}
            className="inline-flex items-center cursor-pointer transition-all duration-200 ease-in-out"
          >
            <span className="flex items-center justify-center w-6 h-6 text-[11px] font-medium text-gray-700 bg-gray-100 rounded-full border border-gray-300 hover:bg-gray-200 hover:text-gray-900 shadow-sm">
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
}
