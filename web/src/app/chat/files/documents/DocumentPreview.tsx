import { FiFileText } from "react-icons/fi";
import { useState, useRef, useEffect } from "react";
import { Tooltip } from "@/components/tooltip/Tooltip";

export function DocumentPreview({
  fileName,
  maxWidth,
}: {
  fileName: string;
  maxWidth?: string;
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
      className="
        flex
        items-center
        p-2
        bg-hover-light
        border
        border-border
        rounded-md
        box-border
        h-16
      "
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
            className={`font-medium text-sm truncate ${
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
