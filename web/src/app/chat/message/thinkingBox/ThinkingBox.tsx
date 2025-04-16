"use client";

import React, { useState, useRef, useEffect } from "react";
import { FiChevronDown, FiChevronUp } from "react-icons/fi";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypePrism from "rehype-prism-plus";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { transformLinkUri } from "@/lib/utils";
import { handleCopy } from "../copyingUtils";
import {
  cleanThinkingContent,
  hasPartialThinkingTokens,
  isThinkingComplete,
} from "../../utils/thinkingTokens";
import "./ThinkingBox.css";

interface ThinkingBoxProps {
  content: string;
  isComplete: boolean;
  isStreaming?: boolean;
}

export const ThinkingBox: React.FC<ThinkingBoxProps> = ({
  content,
  isComplete = false,
  isStreaming = false,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [isTransitioning, setIsTransitioning] = useState(false);

  // DOM refs
  const markdownRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Timing refs
  const startTimeRef = useRef<number | null>(null);

  // Content tracking refs
  const previousContentRef = useRef<string>("");
  const contentLinesRef = useRef<string[]>([]);
  const lastLineCountRef = useRef<number>(0);

  // Token state tracking - separate from streaming state
  const hasOpeningTokenRef = useRef<boolean>(false);
  const hasClosingTokenRef = useRef<boolean>(false);
  const thinkingStoppedTimeRef = useRef<number | null>(null); // Store the exact time when thinking stops

  // Smooth scrolling state
  const targetScrollTopRef = useRef<number>(0);
  const currentScrollTopRef = useRef<number>(0);
  const scrollAnimationRef = useRef<number | null>(null);

  // Clean the thinking content
  const cleanedThinkingContent = cleanThinkingContent(content);

  // Smooth scroll to latest content
  const scrollToLatestContent = () => {
    if (!scrollContainerRef.current) {
      scrollAnimationRef.current = null;
      return;
    }

    const container = scrollContainerRef.current;

    // Calculate how far to move this frame (15% of remaining distance)
    const remainingDistance =
      targetScrollTopRef.current - currentScrollTopRef.current;
    const step = remainingDistance * 0.15;

    // Update position
    currentScrollTopRef.current += step;
    container.scrollTop = Math.round(currentScrollTopRef.current);

    // Continue animation if we're not close enough yet
    if (Math.abs(remainingDistance) > 1) {
      scrollAnimationRef.current = requestAnimationFrame(scrollToLatestContent);
    } else {
      scrollAnimationRef.current = null;
    }
  };

  // Detect thinking token states
  useEffect(() => {
    // For past messages with complete thinking tokens, initialize both as true
    if (
      !hasOpeningTokenRef.current &&
      !hasClosingTokenRef.current &&
      (isComplete || isThinkingComplete(content))
    ) {
      hasOpeningTokenRef.current = true;
      hasClosingTokenRef.current = true;

      // For past messages, set the elapsed time based on content length as an approximation
      const approximateTimeInSeconds = Math.max(
        3, // Minimum 3 seconds
        Math.min(
          Math.floor(cleanedThinkingContent.length / 30), // ~30 chars per second as a rough estimate
          120 // Cap at 2 minutes
        )
      );
      setElapsedTime(approximateTimeInSeconds);
      return;
    }

    // Check if we have the opening token
    if (!hasOpeningTokenRef.current && hasPartialThinkingTokens(content)) {
      hasOpeningTokenRef.current = true;
      startTimeRef.current = Date.now(); // Only set start time when thinking actually begins
    }

    // Check if we have the closing token
    if (
      hasOpeningTokenRef.current &&
      !hasClosingTokenRef.current &&
      isThinkingComplete(content)
    ) {
      hasClosingTokenRef.current = true;
      thinkingStoppedTimeRef.current = Date.now(); // Record exactly when thinking stopped

      // Immediately update elapsed time to final value
      const finalElapsedTime = Math.floor(
        (thinkingStoppedTimeRef.current - startTimeRef.current!) / 1000
      );
      setElapsedTime(finalElapsedTime);
    }
  }, [content, cleanedThinkingContent, isComplete]);

  // Track content changes and new lines
  useEffect(() => {
    // Skip animation for past messages that are already complete
    if (
      hasClosingTokenRef.current &&
      (isComplete || isThinkingComplete(content))
    ) {
      // For past messages, just store the content lines without animating
      const currentLines = cleanedThinkingContent
        .split("\n")
        .filter((line) => line.trim());
      contentLinesRef.current = currentLines;
      previousContentRef.current = cleanedThinkingContent;
      lastLineCountRef.current = currentLines.length;
      return;
    }

    // Don't process if thinking is not active
    if (!hasOpeningTokenRef.current || hasClosingTokenRef.current) return;

    // Process content changes if we have new content
    if (cleanedThinkingContent !== previousContentRef.current) {
      const currentLines = cleanedThinkingContent
        .split("\n")
        .filter((line) => line.trim());
      contentLinesRef.current = currentLines;

      // If we have new lines, update scroll position to show them
      if (
        currentLines.length > lastLineCountRef.current &&
        scrollContainerRef.current
      ) {
        // Calculate position to show the latest content
        const container = scrollContainerRef.current;
        targetScrollTopRef.current =
          container.scrollHeight - container.clientHeight;

        // Start smooth scroll animation if not already running
        if (!scrollAnimationRef.current) {
          currentScrollTopRef.current = container.scrollTop;
          scrollToLatestContent();
        }
      }

      lastLineCountRef.current = currentLines.length;
      previousContentRef.current = cleanedThinkingContent;
    }
  }, [cleanedThinkingContent, content, isComplete]);

  // Update elapsed time
  useEffect(() => {
    // Only count time while thinking is active and we have a start time
    if (
      !hasOpeningTokenRef.current ||
      hasClosingTokenRef.current ||
      startTimeRef.current === null
    )
      return;

    const timer = setInterval(() => {
      // If thinking has stopped, use the final time
      if (thinkingStoppedTimeRef.current) {
        setElapsedTime(
          Math.floor(
            (thinkingStoppedTimeRef.current - startTimeRef.current!) / 1000
          )
        );
        return;
      }

      // Otherwise, use the current time
      setElapsedTime(Math.floor((Date.now() - startTimeRef.current!) / 1000));
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  // Clean up animations on unmount
  useEffect(() => {
    return () => {
      if (scrollAnimationRef.current) {
        cancelAnimationFrame(scrollAnimationRef.current);
        scrollAnimationRef.current = null;
      }
    };
  }, []);

  // Get suitable preview content for collapsed view
  const getPeekContent = () => {
    const lines = contentLinesRef.current;

    if (lines.length <= 3) return lines.join("\n");

    // Show a combination of first and last lines with preference to recent content
    const maxLines = 7;
    const startIndex = Math.max(0, lines.length - maxLines);
    const endIndex = lines.length;

    const previewLines = lines.slice(startIndex, endIndex);
    return previewLines.join("\n");
  };

  // Don't render anything if content is empty
  if (!cleanedThinkingContent.trim()) return null;

  // Determine if thinking is active (has opening token but not closing token)
  const isThinkingActive =
    hasOpeningTokenRef.current && !hasClosingTokenRef.current;

  // Determine if we should show the preview section
  const shouldShowPreview =
    !isExpanded && cleanedThinkingContent.trim().length > 0;
  const hasPreviewContent = getPeekContent().trim().length > 0;

  // Handle toggling with controlled transition
  const handleToggleExpand = () => {
    // Set transitioning state to prevent flashing borders
    setIsTransitioning(true);

    // Small delay before changing expanded state
    setTimeout(() => {
      setIsExpanded(!isExpanded);

      // Keep transition state active during the animation
      setTimeout(() => {
        setIsTransitioning(false);
      }, 250); // Match transition duration in CSS
    }, 10);
  };

  return (
    <div className="thinking-box">
      <div
        className={`thinking-box__container ${
          !isExpanded && "thinking-box__container--collapsed"
        } ${
          (!shouldShowPreview || !hasPreviewContent) &&
          "thinking-box__container--no-preview"
        } ${isTransitioning && "thinking-box__container--transitioning"}`}
      >
        <div className="thinking-box__header" onClick={handleToggleExpand}>
          <div className="thinking-box__title">
            <span className="thinking-box__title-text">
              {isThinkingActive ? "Thinking" : "Thought for"}
            </span>
            <span className="thinking-box__timer">{elapsedTime}s</span>
          </div>
          <div className="thinking-box__collapse-icon">
            {isExpanded ? (
              <FiChevronUp size={16} />
            ) : (
              <FiChevronDown size={16} />
            )}
          </div>
        </div>

        {isExpanded ? (
          <div className="thinking-box__content">
            <div
              ref={markdownRef}
              className="thinking-box__markdown focus:outline-none cursor-text select-text"
              onCopy={(e) => handleCopy(e, markdownRef)}
            >
              <ReactMarkdown
                className="prose dark:prose-invert max-w-full"
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[
                  [rehypePrism, { ignoreMissing: true }],
                  rehypeKatex,
                ]}
                urlTransform={transformLinkUri}
              >
                {cleanedThinkingContent}
              </ReactMarkdown>
            </div>
          </div>
        ) : (
          shouldShowPreview &&
          hasPreviewContent && (
            <div
              className={`thinking-box__preview ${
                isThinkingActive ? "thinking-box__preview--crawling" : ""
              }`}
            >
              <div className="thinking-box__fade-container">
                <div
                  ref={scrollContainerRef}
                  className="thinking-box__scroll-content"
                >
                  <pre className="thinking-box__preview-text">
                    {getPeekContent()}
                  </pre>
                </div>
              </div>
            </div>
          )
        )}
      </div>
    </div>
  );
};

export default ThinkingBox;
