"use client";

import { useState, useMemo, useRef, useLayoutEffect, useEffect } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import Modal from "@/refresh-components/Modal";
import IconButton from "@/refresh-components/buttons/IconButton";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import Text from "@/refresh-components/texts/Text";
import { SvgDownload, SvgMaximize2, SvgX } from "@opal/icons";
import { cn } from "@/lib/utils";

export interface ExpandableTextDisplayProps {
  /** Title shown in header and modal */
  title: string;
  /** The full text content to display (used in modal and for copy/download) */
  content: string;
  /** Optional content to display in collapsed view (e.g., for streaming animation). Falls back to `content`. */
  displayContent?: string;
  /** Subtitle text (e.g., file size). If not provided, calculates from content */
  subtitle?: string;
  /** Maximum lines to show in collapsed state (1-6). Values outside this range default to 5. */
  maxLines?: 1 | 2 | 3 | 4 | 5 | 6;
  /** Additional className for the container */
  className?: string;
  /** Optional custom renderer for content (e.g., markdown). Falls back to plain text. */
  renderContent?: (content: string) => React.ReactNode;
  /** When true, uses scrollable container with auto-scroll instead of line-clamp */
  isStreaming?: boolean;
}

/** Calculate content size in human-readable format */
function getContentSize(text: string): string {
  const bytes = new Blob([text]).size;
  if (bytes < 1024) return `${bytes} Bytes`;
  return `${(bytes / 1024).toFixed(2)} KB`;
}

/** Count lines in text */
function getLineCount(text: string): number {
  return text.split("\n").length;
}

/** Download content as a .txt file */
function downloadAsTxt(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Approximate line height for max-height calculation in streaming mode */
const LINE_HEIGHT_PX = 20;

export default function ExpandableTextDisplay({
  title,
  content,
  displayContent,
  subtitle,
  maxLines = 1,
  className,
  renderContent,
  isStreaming = false,
}: ExpandableTextDisplayProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isTruncated, setIsTruncated] = useState(false);
  const textRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevIsStreamingRef = useRef(isStreaming);

  const lineCount = useMemo(() => getLineCount(content), [content]);
  const contentSize = useMemo(() => getContentSize(content), [content]);
  const displaySubtitle = subtitle ?? contentSize;

  useLayoutEffect(() => {
    // Use scrollRef for streaming mode or when renderContent is provided (max-height approach)
    // Use textRef only for plain text with line-clamp
    const el =
      isStreaming || renderContent ? scrollRef.current : textRef.current;
    if (el) {
      setIsTruncated(el.scrollHeight > el.clientHeight);
    }
  }, [content, displayContent, maxLines, isStreaming, renderContent]);

  // Auto-scroll to bottom when streaming, reset to top when streaming ends
  // Use useEffect (not useLayoutEffect) to ensure content is fully rendered before scrolling
  useEffect(() => {
    if (isStreaming && scrollRef.current) {
      // Auto-scroll to bottom during streaming
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    } else if (
      prevIsStreamingRef.current &&
      !isStreaming &&
      scrollRef.current
    ) {
      // When streaming just ended, reset scroll to top
      scrollRef.current.scrollTop = 0;
    }
    prevIsStreamingRef.current = isStreaming;
  }, [isStreaming, content, displayContent]);

  const handleDownload = () => {
    const sanitizedTitle = title.replace(/[^a-z0-9]/gi, "_").toLowerCase();
    downloadAsTxt(content, sanitizedTitle);
  };

  const lineClampClassMap: Record<number, string> = {
    1: "line-clamp-1",
    2: "line-clamp-2",
    3: "line-clamp-3",
    4: "line-clamp-4",
    5: "line-clamp-5",
    6: "line-clamp-6",
  };
  const lineClampClass = lineClampClassMap[maxLines] ?? "line-clamp-5";

  return (
    <>
      {/* Collapsed View */}
      <div className={cn("w-full flex bg-red-400", className)}>
        {(() => {
          // Build the content element
          const contentElement =
            isStreaming || renderContent ? (
              // Streaming mode: scrollable container with auto-scroll
              // Rendered content (markdown): use max-height + overflow-hidden
              // (line-clamp uses display: -webkit-box which conflicts with complex HTML)
              <div
                ref={scrollRef}
                className={cn(
                  isStreaming
                    ? "overflow-y-auto no-scrollbar"
                    : "overflow-hidden",
                  !renderContent && "whitespace-pre-wrap"
                )}
                style={{ maxHeight: `${maxLines * LINE_HEIGHT_PX}px` }}
              >
                {renderContent ? (
                  renderContent(displayContent ?? content)
                ) : (
                  <Text as="p" mainUiMuted text03>
                    {displayContent ?? content}
                  </Text>
                )}
              </div>
            ) : (
              // Static mode with plain text: use line-clamp
              <div
                ref={textRef}
                className={cn(lineClampClass, "whitespace-pre-wrap")}
              >
                <Text as="p" mainUiMuted text03>
                  {displayContent ?? content}
                </Text>
              </div>
            );

          return contentElement;
        })()}

        {/* Expand button - only show when content is truncated */}
        {isTruncated && (
          <div className="flex items-end mt-1">
            <IconButton
              internal
              icon={SvgMaximize2}
              tooltip="View Full Text"
              onClick={() => setIsModalOpen(true)}
            />
          </div>
        )}
      </div>

      {/* Expanded Modal */}
      <Modal open={isModalOpen} onOpenChange={setIsModalOpen}>
        <Modal.Content height="lg" width="md-sm" preventAccidentalClose={false}>
          {/* Header */}
          <div className="flex items-start justify-between px-4 py-3">
            <div className="flex flex-col">
              <DialogPrimitive.Title asChild>
                <Text as="span" text04 headingH3>
                  {title}
                </Text>
              </DialogPrimitive.Title>
              <DialogPrimitive.Description asChild>
                <Text as="span" text03 secondaryBody>
                  {displaySubtitle}
                </Text>
              </DialogPrimitive.Description>
            </div>
            <DialogPrimitive.Close asChild>
              <IconButton
                icon={SvgX}
                internal
                onClick={() => setIsModalOpen(false)}
              />
            </DialogPrimitive.Close>
          </div>

          {/* Body */}
          <Modal.Body>
            {renderContent ? (
              renderContent(content)
            ) : (
              <Text as="p" mainUiMuted text03 className="whitespace-pre-wrap">
                {content}
              </Text>
            )}
          </Modal.Body>

          {/* Footer */}
          <div className="flex items-center justify-between p-2 bg-background-tint-01">
            <div className="px-2">
              <Text as="span" mainUiMuted text03>
                {lineCount} {lineCount === 1 ? "line" : "lines"}
              </Text>
            </div>
            <div className="flex items-center gap-1 bg-background-tint-00 p-1 rounded-12">
              <CopyIconButton
                internal
                getCopyText={() => content}
                tooltip="Copy"
              />
              <IconButton
                internal
                icon={SvgDownload}
                tooltip="Download"
                onClick={handleDownload}
              />
            </div>
          </div>
        </Modal.Content>
      </Modal>
    </>
  );
}
