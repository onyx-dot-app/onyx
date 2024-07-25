import { FiFileText } from "react-icons/fi";
import { useState, useRef, useEffect } from "react";
import { Tooltip } from "@/components/tooltip/Tooltip";

export function DocumentPreview({
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
        h-16
      `}
    >
      <div className="flex-shrink-0">
        <div
          className="
            w-12
            h-12
            bg-document
            flex
            items-center
            justify-center
            rounded-md
          "
        >
          <FiFileText className="w-6 h-6 text-white" />
        </div>
      </div>
      <div className="ml-4 relative">
        <Tooltip content={fileName} side="top" align="start">
          <div
            ref={fileNameRef}
            className={`font-medium text-sm line-clamp-1 break-all ellipses ${
              maxWidth ? maxWidth : "max-w-48"
            }`}
          >
            {fileName}
          </div>
        </Tooltip>
        <div className="text-subtle text-sm">Document</div>
      </div>
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
        <Tooltip content={fileName} side="top" align="start">
          <div
            ref={fileNameRef}
            className={`font-medium text-sm line-clamp-1 break-all ellipses ${
              maxWidth ? maxWidth : "max-w-48"
            }`}
          >
            {fileName}
          </div>
        </Tooltip>
      </div>
    </div>
  );
}
