import { FiFileText } from "react-icons/fi";
import { useState, useRef, useEffect } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ExpandTwoIcon } from "@/components/icons/icons";

export function DocumentPreview({
  fileName,
  maxWidth,
  alignBubble,
  open,
}: {
  fileName: string;
  open?: () => void;
  maxWidth?: string;
  alignBubble?: boolean;
}) {
  const fileNameRef = useRef<HTMLDivElement>(null);

  return (
    <div
      className={`
        ${alignBubble && "w-64"}
        flex
        items-center
        p-3
        bg-hover
        border
        border-border
        rounded-lg
        box-border
        h-20
        hover:shadow-sm
        transition-all
      `}
    >
      <div className="flex-shrink-0">
        <div
          className="
            w-14
            h-14
            bg-document
            flex
            items-center
            justify-center
            rounded-lg
            transition-all
            duration-200
            hover:bg-document-dark
          "
        >
          <FiFileText className="w-7 h-7 text-white" />
        </div>
      </div>
      <div className="ml-4 flex-grow">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <div
                ref={fileNameRef}
                className={`font-medium text-sm line-clamp-1 break-all ellipsis ${
                  maxWidth ? maxWidth : "max-w-48"
                }`}
              >
                {fileName}
              </div>
            </TooltipTrigger>
            <TooltipContent side="top" align="start">
              {fileName}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
        <div className="text-subtle text-xs mt-1">Document</div>
      </div>
      {open && (
        <button
          onClick={() => open()}
          className="ml-2 p-2 rounded-full hover:bg-gray-200 transition-colors duration-200"
          aria-label="Expand document"
        >
          <ExpandTwoIcon className="w-5 h-5 text-gray-600" />
        </button>
      )}
    </div>
  );
}

export function InputDocumentPreview({
  fileName,
  maxWidth,
  alignBubble,
}: {
  fileName: string;
  maxWidth?: string;
  alignBubble?: boolean;
}) {
  const [isOverflowing, setIsOverflowing] = useState(false);
  const fileNameRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (fileNameRef.current) {
      setIsOverflowing(
        fileNameRef.current.scrollWidth > fileNameRef.current.clientWidth
      );
    }
  }, [fileName]);

  return (
    <div
      className={`
        ${alignBubble && "w-64"}
        flex
        items-center
        p-2
        bg-hover
        border
        border-border
        rounded-md
        box-border
        h-10
      `}
    >
      <div className="flex-shrink-0">
        <div
          className="
            w-6
            h-6
            bg-document
            flex
            items-center
            justify-center
            rounded-md
          "
        >
          <FiFileText className="w-4 h-4 text-white" />
        </div>
      </div>
      <div className="ml-2 relative">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <div
                ref={fileNameRef}
                className={`font-medium text-sm line-clamp-1 break-all ellipses ${
                  maxWidth ? maxWidth : "max-w-48"
                }`}
              >
                {fileName}
              </div>
            </TooltipTrigger>
            <TooltipContent side="top" align="start">
              {fileName}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
    </div>
  );
}
