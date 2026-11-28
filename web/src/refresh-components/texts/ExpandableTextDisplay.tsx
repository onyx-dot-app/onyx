"use client";

import { useState, useMemo, useRef, useEffect, useLayoutEffect } from "react";
import { useTranslations } from "next-intl";
import { useFormatBytes } from "@/hooks/useFormatBytes";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Text, Modal } from "@opal/components";
import { CopyButton } from "@opal/components";
import { SvgDownload, SvgMaximize2, SvgX } from "@opal/icons";
import { Button } from "@opal/components";
import { cn } from "@opal/utils";

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
  /** Renders plain text (without `renderContent`) in the monospace font, e.g. for command output */
  monospace?: boolean;
}

/** Count lines in text */
function getLineCount(text: string): number {
  return text.split("\n").length;
}

/** Extract the last N lines from text for streaming display.
 * When truncated, returns (maxLines - 1) lines to leave room for ellipsis.
 * Scans back from the end, so the cost follows the lines shown, not the text
 * length.
 */
function getLastLines(
  text: string,
  maxLines: number
): { lines: string; hasTruncation: boolean } {
  let searchFrom = text.length - 1;
  let shownStart = 0;
  for (let newlines = 1; newlines <= maxLines; newlines++) {
    const newline = searchFrom < 0 ? -1 : text.lastIndexOf("\n", searchFrom);
    if (newline === -1) {
      return { lines: text, hasTruncation: false };
    }
    // Reserve one line for ellipsis, show last (maxLines - 1) content lines
    if (newlines === maxLines - 1) {
      shownStart = newline + 1;
    }
    searchFrom = newline - 1;
  }
  return {
    lines: maxLines > 1 ? text.slice(shownStart) : "",
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
  monospace = false,
}: ExpandableTextDisplayProps) {
  const t = useTranslations("common.expandableText");
  const formatBytes = useFormatBytes();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isMeasuredTruncated, setIsMeasuredTruncated] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentInnerRef = useRef<HTMLDivElement>(null);
  const plainTextFont = monospace ? "secondary-mono" : "main-ui-muted";
  const hasRenderContent = renderContent !== undefined;

  // Only the modal shows these, so streamed text is not re-measured per update.
  const lineCount = useMemo(
    () => (isModalOpen ? getLineCount(content) : 0),
    [isModalOpen, content]
  );
  const contentSize = useMemo(
    () => (isModalOpen ? formatBytes(new Blob([content]).size) : ""),
    [isModalOpen, content, formatBytes]
  );
  const displaySubtitle = subtitle ?? contentSize;

  const plainStreamingTail = useMemo(
    () =>
      isStreaming && !hasRenderContent
        ? getLastLines(displayContent ?? content, maxLines)
        : null,
    [isStreaming, hasRenderContent, displayContent, content, maxLines]
  );
  const isTruncated = plainStreamingTail
    ? plainStreamingTail.hasTruncation
    : isMeasuredTruncated;

  // Truncation detection (read-only, doesn't need to block paint). The end of
  // a stream swaps the container, so isStreaming re-runs the measure.
  useEffect(() => {
    if (!plainStreamingTail && scrollRef.current) {
      setIsMeasuredTruncated(
        scrollRef.current.scrollHeight > scrollRef.current.clientHeight
      );
    }
  }, [
    plainStreamingTail,
    isStreaming,
    renderContent,
    content,
    displayContent,
    maxLines,
  ]);

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
            <Text as="p" color="text-03" font="main-ui-muted">
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
  const renderPlainTextStreaming = ({
    lines,
    hasTruncation,
  }: ReturnType<typeof getLastLines>) => (
    <div ref={scrollRef} className="overflow-hidden">
      {hasTruncation && (
        <Text as="span" font={plainTextFont} color="text-03">
          {"…\n"}
        </Text>
      )}
      <div className="whitespace-pre-wrap">
        <Text as="p" font={plainTextFont} color="text-03">
          {lines}
        </Text>
      </div>
    </div>
  );

  // Render plain text static (CSS line-clamp + scroll-based truncation detection)
  const renderPlainTextStatic = () => (
    <div
      ref={scrollRef}
      className={cn("overflow-hidden whitespace-pre-wrap", lineClampClass)}
    >
      {/* A block: the padding of an inline span would indent only the first line */}
      <Text as="p" font={plainTextFont} color="text-03">
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
            : plainStreamingTail
              ? renderPlainTextStreaming(plainStreamingTail)
              : renderPlainTextStatic()}
        </div>

        {/* Expand button - only show when content is truncated */}

        <div className="flex justify-end self-end mt-1 w-8">
          {isTruncated && (
            <Button
              prominence="tertiary"
              size="sm"
              icon={SvgMaximize2}
              tooltip={t("viewFullButton.tooltip")}
              onClick={() => setIsModalOpen(true)}
            />
          )}
        </div>
      </div>

      {/* Expanded Modal */}
      <Modal open={isModalOpen} onOpenChange={setIsModalOpen}>
        <Modal.Content height="lg" width="lg" preventAccidentalClose={false}>
          {/* Header */}
          <div className="flex items-start justify-between px-4 py-3">
            <div className="flex flex-col">
              <DialogPrimitive.Title asChild>
                <Text as="span" color="text-04" font="heading-section">
                  {title}
                </Text>
              </DialogPrimitive.Title>
              <DialogPrimitive.Description asChild>
                <Text as="span" color="text-03" font="secondary-body">
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
              <div className="whitespace-pre-wrap">
                <Text as="p" font={plainTextFont} color="text-03">
                  {content}
                </Text>
              </div>
            )}
          </Modal.Body>

          {/* Footer */}
          <div className="flex items-center justify-between p-2 bg-background-tint-01">
            <div className="px-2">
              <Text as="span" font="main-ui-muted" color="text-03">
                {t("lineCount.label", { count: lineCount })}
              </Text>
            </div>
            <div className="flex items-center gap-1 bg-background-tint-00 p-1 rounded-12">
              <CopyButton
                prominence="tertiary"
                size="sm"
                getCopyText={() => content}
                tooltip={t("copyButton.tooltip")}
              />
              <Button
                prominence="tertiary"
                size="sm"
                icon={SvgDownload}
                tooltip={t("downloadButton.tooltip")}
                onClick={handleDownload}
              />
            </div>
          </div>
        </Modal.Content>
      </Modal>
    </>
  );
}
