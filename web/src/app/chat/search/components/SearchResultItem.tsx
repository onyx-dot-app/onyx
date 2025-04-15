import React from "react";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ResultIcon } from "@/components/chat/sources/SourceCard";
import { getTimeAgoString } from "@/lib/dateUtils";
import { FiThumbsUp, FiUser, FiClock, FiCalendar } from "react-icons/fi";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface SearchResultItemProps {
  document: OnyxDocument;
  onClick: (document: OnyxDocument) => void;
}

export function SearchResultItem({ document, onClick }: SearchResultItemProps) {
  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    onClick(document);
  };

  // Format the update date if available
  const updatedAtFormatted = document.updated_at
    ? getTimeAgoString(new Date(document.updated_at))
    : "";

  console.log(JSON.stringify(document));
  return (
    <div
      className="border-b border-gray-200 py-4 hover:bg-gray-50 px-4 cursor-pointer"
      onClick={handleClick}
    >
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 mt-1">
          <ResultIcon doc={document} size={20} />
        </div>

        <div className="flex-grow">
          <div className="flex items-center gap-2">
            <h3
              className="text-base font-medium text-gray-900 line-clamp-1 hover:underline cursor-pointer"
              onClick={handleClick}
            >
              {document.semantic_identifier || "Untitled Document"}
            </h3>
          </div>
          <div className="flex items-center gap-3 my-1.5  text-xs text-gray-500">
            {document.boost > 1 && (
              <span className="text-xs bg-gray-100 px-2 py-0.5 rounded-full text-gray-500">
                Matched
              </span>
            )}
            {document.primary_owners && document.primary_owners.length > 0 && (
              <span className="text-xs flex items-center gap-1">
                <FiUser size={12} />
                {document.primary_owners.length === 1 ? (
                  document.primary_owners[0]
                ) : (
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger className="cursor-help">
                        {document.primary_owners.length} Owners
                      </TooltipTrigger>
                      <TooltipContent>
                        {document.primary_owners.join(", ")}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                )}
              </span>
            )}
            {updatedAtFormatted && (
              <span className="flex items-center gap-1">
                <FiClock size={12} />
                <span>Updated {updatedAtFormatted}</span>
              </span>
            )}
            {document.metadata?.helpful && (
              <span className="flex items-center gap-1">
                <FiThumbsUp size={12} />
                <span>Helpful</span>
              </span>
            )}
          </div>
          <p className="text-sm text-gray-700 line-clamp-2">
            {document.blurb || "No description available"}
          </p>
        </div>
      </div>
    </div>
  );
}
