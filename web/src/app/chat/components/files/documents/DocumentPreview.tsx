import { useState, useRef, useEffect, useMemo } from "react";
import { ExpandTwoIcon } from "@/components/icons/icons";
import Truncated from "@/refresh-components/Truncated";
import Text from "@/refresh-components/Text";
import SvgFileText from "@/icons/file-text";

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
  const typeLabel = useMemo(() => {
    const name = String(fileName || "");
    const lastDotIndex = name.lastIndexOf(".");
    if (lastDotIndex <= 0 || lastDotIndex === name.length - 1) {
      return "";
    }
    return name.slice(lastDotIndex + 1).toUpperCase();
  }, [fileName]);

  return (
    <div
      className={`relative group flex items-center gap-3 border border-border-01 rounded-12 bg-background-tint-00 p-spacing-inline h-14${
        open ? "cursor-pointer hover:bg-accent-background" : ""
      }`}
      onClick={() => {
        if (open) {
          open();
        }
      }}
    >
      <div className="flex h-9 w-9 items-center justify-center rounded-08 bg-background-tint-01">
        <SvgFileText className="h-5 w-5 stroke-text-02" />
      </div>
      <div className="flex flex-col overflow-hidden w-40">
        <Truncated
          className="font-secondary-action text-text-04"
          title={fileName}
        >
          {fileName}
        </Truncated>
        <Text text03 secondaryBody>
          {typeLabel || "Document"}
        </Text>
      </div>
      {open && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            open();
          }}
          className="absolute -left-2 -top-2 z-10 h-5 w-5 flex items-center justify-center rounded-[4px] border border-border text-[11px] bg-[#1f1f1f] text-white dark:bg-[#fefcfa] dark:text-black shadow-sm opacity-0 group-hover:opacity-100 focus:opacity-100 pointer-events-none group-hover:pointer-events-auto focus:pointer-events-auto transition-opacity duration-150 hover:opacity-90"
          aria-label="Expand document"
        >
          <ExpandTwoIcon className="h-4 w-4 dark:text-dark-tremor-background-muted" />
        </button>
      )}
    </div>
  );
}
