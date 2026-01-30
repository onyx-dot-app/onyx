"use client";

import { useState, useMemo, useRef, useLayoutEffect, useEffect } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import TruncateMarkup from "react-truncate-markup";
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
  /** Optional custom renderer for content (e.g., markdown). Falls back to plain text.
   * @param content - The text content to render
   * @param isExpanded - Whether the content is being rendered in expanded (modal) view
   */
  renderContent?: (content: string, isExpanded: boolean) => React.ReactNode;
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

/** Approximate line height for max-height calculation */
const LINE_HEIGHT_PX = 20;

export default function ExpandableTextDisplay({
  title,
  content,
  displayContent,
  subtitle,
  maxLines = 5,
  className,
  renderContent,
  isStreaming = false,
}: ExpandableTextDisplayProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isTruncated, setIsTruncated] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevIsStreamingRef = useRef(isStreaming);

  const lineCount = useMemo(() => getLineCount(content), [content]);
  const contentSize = useMemo(() => getContentSize(content), [content]);
  const displaySubtitle = subtitle ?? contentSize;

  // Detect truncation for renderContent mode (both streaming and static)
  // (TruncateMarkup's onTruncate handles plain text static mode)
  useLayoutEffect(() => {
    if (renderContent && scrollRef.current) {
      // For renderContent, always use scrollRef (same container for streaming and static)
      setIsTruncated(
        scrollRef.current.scrollHeight > scrollRef.current.clientHeight
      );
    } else if (isStreaming && scrollRef.current) {
      // Plain text streaming mode
      setIsTruncated(
        scrollRef.current.scrollHeight > scrollRef.current.clientHeight
      );
    }
  }, [isStreaming, renderContent, content, displayContent, maxLines]);

  // Auto-scroll to bottom when streaming, reset to top when streaming ends
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

  // Handle truncation callback from TruncateMarkup (static mode only)
  const handleTruncate = (wasTruncated: boolean) => {
    setIsTruncated(wasTruncated);
  };

  const handleDownload = () => {
    const sanitizedTitle = title.replace(/[^a-z0-9]/gi, "_").toLowerCase();
    downloadAsTxt(content, sanitizedTitle);
  };

  // Map maxLines to Tailwind line-clamp classes
  const lineClampClass = {
    1: "line-clamp-1",
    2: "line-clamp-2",
    3: "line-clamp-3",
    4: "line-clamp-4",
    5: "line-clamp-5",
    6: "line-clamp-6",
  }[maxLines];

  // Single container for renderContent mode (both streaming and static)
  // Keeps scrollRef alive across the streaming → static transition so scroll reset works
  const renderContentWithRef = () => (
    <div
      ref={scrollRef}
      className={cn(
        "no-scrollbar",
        isStreaming ? "overflow-y-auto" : lineClampClass
      )}
      style={
        isStreaming
          ? { maxHeight: `${maxLines * LINE_HEIGHT_PX}px` }
          : undefined
      }
    >
      {renderContent!(displayContent ?? content, false)}
    </div>
  );

  // Render plain text streaming (scrollable)
  const renderPlainTextStreaming = () => (
    <div
      ref={scrollRef}
      className="overflow-y-auto no-scrollbar"
      style={{ maxHeight: `${maxLines * LINE_HEIGHT_PX}px` }}
    >
      <Text as="p" mainUiMuted text03 className="whitespace-pre-wrap">
        {displayContent ?? content}
      </Text>
    </div>
  );

  // Render plain text static (TruncateMarkup for reliable truncation)
  const renderPlainTextStatic = () => (
    <TruncateMarkup lines={maxLines} ellipsis="…" onTruncate={handleTruncate}>
      <div className="whitespace-pre-wrap">
        <Text as="p" mainUiMuted text03>
          {displayContent ?? content}
        </Text>
      </div>
    </TruncateMarkup>
  );

  return (
    <>
      {/* Collapsed View */}
      <div className={cn("w-full flex", className)}>
        {renderContent
          ? renderContentWithRef()
          : isStreaming
            ? renderPlainTextStreaming()
            : renderPlainTextStatic()}

        {/* Expand button - only show when content is truncated */}

        <div className="flex items-end mt-1 w-8">
          {isTruncated && (
            <IconButton
              internal
              icon={SvgMaximize2}
              tooltip="View Full Text"
              onClick={() => setIsModalOpen(true)}
            />
          )}
        </div>
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
              renderContent(content, true)
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
