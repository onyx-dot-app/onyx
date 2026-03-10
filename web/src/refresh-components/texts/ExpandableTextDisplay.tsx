"use client";

import { useState, useMemo, useRef, useEffect, useLayoutEffect } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import Modal from "@/refresh-components/Modal";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import Text from "@/refresh-components/texts/Text";
import { SvgDownload, SvgMaximize2, SvgX } from "@opal/icons";
import { Button } from "@opal/components";
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
  /** Maximum lines to show in collapsed state (1-10). Values outside this range default to 8. */
  maxLines?: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10;
  /** Additional className for the container */
  className?: string;
  /** Optional custom renderer for content (e.g., markdown). Falls back to plain text.
   * @param content - The text content to render
   * @param isExpanded - Whether the content is being rendered in expanded (modal) view
   */
  renderContent?: (content: string, isExpanded: boolean) => React.ReactNode;
  /** When true, shows last N lines with top-truncation (ellipsis at top) instead of bottom-truncation */
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

/** Extract the last N lines from text for streaming display.
 * When truncated, returns (maxLines - 1) lines to leave room for ellipsis.
 */
function getLastLines(
  text: string,
  maxLines: number
): { lines: string; hasTruncation: boolean } {
  const allLines = text.split("\n");
  if (allLines.length <= maxLines) {
    return { lines: text, hasTruncation: false };
  }
  // Reserve one line for ellipsis, show last (maxLines - 1) content lines
  const linesToShow = maxLines - 1;
  if (linesToShow <= 0) {
    return { lines: "", hasTruncation: true };
  }
  return {
    lines: allLines.slice(-linesToShow).join("\n"),
    hasTruncation: true,
  };
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

/** Block-level HTML tags used by the snap algorithm to recurse into containers. */
const CONTAINER_TAGS = new Set([
  "UL",
  "OL",
  "LI",
  "BLOCKQUOTE",
  "DIV",
  "DL",
  "DD",
  "TABLE",
  "TBODY",
  "THEAD",
  "TR",
  "TH",
  "TD",
  "SECTION",
  "DETAILS",
  "PRE",
  "FIGURE",
  "FIGCAPTION",
  "ARTICLE",
  "ASIDE",
  "HEADER",
  "FOOTER",
  "MAIN",
  "NAV",
]);

export default function ExpandableTextDisplay({
  title,
  content,
  displayContent,
  subtitle,
  maxLines = 8,
  className,
  renderContent,
  isStreaming = false,
}: ExpandableTextDisplayProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isTruncated, setIsTruncated] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentInnerRef = useRef<HTMLDivElement>(null);

  const lineCount = useMemo(() => getLineCount(content), [content]);
  const contentSize = useMemo(() => getContentSize(content), [content]);
  const displaySubtitle = subtitle ?? contentSize;

  // Truncation detection (read-only, doesn't need to block paint)
  useEffect(() => {
    if (renderContent && scrollRef.current) {
      setIsTruncated(
        scrollRef.current.scrollHeight > scrollRef.current.clientHeight
      );
    } else if (isStreaming) {
      const textToCheck = displayContent ?? content;
      setIsTruncated(getLineCount(textToCheck) > maxLines);
    } else if (scrollRef.current) {
      setIsTruncated(
        scrollRef.current.scrollHeight > scrollRef.current.clientHeight
      );
    }
  }, [isStreaming, renderContent, content, displayContent, maxLines]);

  // Shift content upward during streaming for renderContent mode,
  // snapping to element boundaries so blocks are never partially clipped.
  // Must block paint to avoid flicker.
  useLayoutEffect(() => {
    if (
      !isStreaming ||
      !renderContent ||
      !scrollRef.current ||
      !contentInnerRef.current
    ) {
      return;
    }

    const containerHeight = scrollRef.current.clientHeight;
    const contentHeight = contentInnerRef.current.scrollHeight;
    let overflow = Math.max(0, contentHeight - containerHeight);

    if (overflow > 0) {
      let blockParent: Element = contentInnerRef.current;
      while (
        blockParent.children.length === 1 &&
        blockParent.children[0]!.children.length > 0
      ) {
        blockParent = blockParent.children[0]!;
      }

      contentInnerRef.current.style.transform = "translateY(0)";
      const refTop = contentInnerRef.current.getBoundingClientRect().top;

      let snapParent: Element = blockParent;
      let snap = overflow;
      while (true) {
        let found = false;
        for (let i = 0; i < snapParent.children.length; i++) {
          const child = snapParent.children[i] as HTMLElement;
          const rect = child.getBoundingClientRect();
          const top = rect.top - refTop;
          const bottom = top + rect.height;
          if (top < snap && snap < bottom) {
            if (
              child.children.length > 0 &&
              CONTAINER_TAGS.has(child.tagName)
            ) {
              snapParent = child;
              found = true;
              break;
            }
            snap = bottom;
            found = true;
            break;
          }
        }
        if (!found) break;
        if (snap !== overflow) break;
      }
      overflow = snap;
    }

    contentInnerRef.current.style.transform =
      overflow > 0 ? `translateY(-${overflow}px)` : "translateY(0)";
  }, [isStreaming, renderContent, content, displayContent, maxLines]);

  const handleDownload = () => {
    const sanitizedTitle = title.replace(/[^a-z0-9]/gi, "_").toLowerCase();
    downloadAsTxt(content, sanitizedTitle);
  };

  // Map maxLines to Tailwind line-clamp classes (fallback to 8 for invalid runtime values)
  const lineClampClass =
    {
      1: "line-clamp-1",
      2: "line-clamp-2",
      3: "line-clamp-3",
      4: "line-clamp-4",
      5: "line-clamp-5",
      6: "line-clamp-6",
      7: "line-clamp-7",
      8: "line-clamp-8",
      9: "line-clamp-9",
      10: "line-clamp-10",
    }[maxLines] ?? "line-clamp-8";

  // Single container for renderContent mode (both streaming and static)
  // Keeps scrollRef alive across the streaming → static transition
  const renderContentWithRef = () => {
    const textToDisplay = displayContent ?? content;

    if (isStreaming) {
      // During streaming: use max-height with overflow-hidden and CSS transform to shift
      // content upward, showing the latest content from the bottom without scroll jitter.
      // Line height is approximately 1.5rem (24px) for body text.
      // We show a top ellipsis indicator when content is truncated.
      return (
        <div>
          {isTruncated && (
            <Text as="p" text03 mainUiMuted className="!my-0">
              …
            </Text>
          )}
          <div
            ref={scrollRef}
            className="overflow-hidden"
            style={{ maxHeight: `calc(${maxLines} * 1.5rem)` }}
          >
            <div ref={contentInnerRef}>
              {renderContent!(textToDisplay, false)}
            </div>
          </div>
        </div>
      );
    }

    // Static mode: use CSS line-clamp for bottom truncation
    return (
      <div ref={scrollRef} className={cn("overflow-hidden", lineClampClass)}>
        {renderContent!(textToDisplay, false)}
      </div>
    );
  };

  // Render plain text streaming (top-truncation with last N lines)
  const renderPlainTextStreaming = () => {
    const textToDisplay = displayContent ?? content;
    const { lines, hasTruncation } = getLastLines(textToDisplay, maxLines);

    return (
      <div ref={scrollRef} className="overflow-hidden">
        {hasTruncation && (
          <Text as="span" mainUiMuted text03>
            …{"\n"}
          </Text>
        )}
        <Text as="p" mainUiMuted text03 className="whitespace-pre-wrap">
          {lines}
        </Text>
      </div>
    );
  };

  // Render plain text static (CSS line-clamp + scroll-based truncation detection)
  const renderPlainTextStatic = () => (
    <div ref={scrollRef} className={cn("overflow-hidden", lineClampClass)}>
      <Text as="span" mainUiMuted text03 className="whitespace-pre-wrap">
        {displayContent ?? content}
      </Text>
    </div>
  );

  return (
    <>
      {/* Collapsed View */}
      <div className={cn("w-full flex", className)}>
        <div className="flex-1 min-w-0">
          {renderContent
            ? renderContentWithRef()
            : isStreaming
              ? renderPlainTextStreaming()
              : renderPlainTextStatic()}
        </div>

        {/* Expand button - only show when content is truncated */}

        <div className="flex justify-end self-end mt-1 w-8">
          {isTruncated && (
            <Button
              prominence="tertiary"
              size="sm"
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
              <Button
                icon={SvgX}
                prominence="tertiary"
                size="sm"
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
                prominence="tertiary"
                size="sm"
                getCopyText={() => content}
                tooltip="Copy"
              />
              <Button
                prominence="tertiary"
                size="sm"
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
