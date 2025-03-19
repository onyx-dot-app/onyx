"use client";

import React, { useState, useRef, useEffect } from "react";
import { FiChevronDown, FiChevronUp } from "react-icons/fi";
import { TbBrain } from "react-icons/tb";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypePrism from "rehype-prism-plus";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { transformLinkUri } from "@/lib/utils";
import { handleCopy } from "./copyingUtils";
import { cleanThinkingContent } from "../utils/thinkingTokens";
import "./ThinkingBox.css";

interface ThinkingBoxProps {
  content: string;
  isComplete: boolean;
  autoCollapse?: boolean;
  isStreaming?: boolean;
}

export const ThinkingBox: React.FC<ThinkingBoxProps> = ({
  content,
  isComplete,
  autoCollapse = true,
  isStreaming = !isComplete,
}) => {
  const [isExpanded, setIsExpanded] = useState(false); // Always start collapsed
  const [elapsedTime, setElapsedTime] = useState(0);
  const markdownRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const startTimeRef = useRef<number>(Date.now());
  const lastContentRef = useRef<string>(""); // Track content changes
  const animationRef = useRef<number | null>(null); // Track animation frame
  const positionRef = useRef<number>(0); // Store scroll position between updates
  const isAnimatingRef = useRef<boolean>(false); // Track animation state
  
  // Clean the thinking content (remove <think> tags)
  const cleanedThinkingContent = cleanThinkingContent(content);

  // Update elapsed time
  useEffect(() => {
    if (!isStreaming || isComplete) return;
    
    const timer = setInterval(() => {
      setElapsedTime(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);
    
    return () => clearInterval(timer);
  }, [isStreaming, isComplete]);

  // Get suitable preview content for collapsed view
  const getPeekContent = () => {
    const lines = cleanedThinkingContent.split('\n').filter(line => line.trim());
    
    if (lines.length <= 3) return lines.join('\n');
    
    // Always show the most recent content, with preference to the end of the text
    // This ensures that as new tokens arrive, we see the latest thinking
    const maxLines = 5;
    const startIndex = Math.max(0, lines.length - maxLines);
    const endIndex = lines.length;
    
    const previewLines = lines.slice(startIndex, endIndex);
    return previewLines.join('\n');
  };

  // Animation function that preserves scroll position
  const animate = () => {
    if (!scrollContainerRef.current) return;
    
    const container = scrollContainerRef.current;
    const maxScroll = Math.max(1, container.scrollHeight - container.clientHeight);
    
    // Don't animate if there's no scrollable content
    if (maxScroll <= 1) {
      animationRef.current = requestAnimationFrame(animate);
      return;
    }
    
    // Keep scroll position even when content changes
    const scrollSpeed = 2.5; // Speed of scrolling
    positionRef.current = (positionRef.current + scrollSpeed) % (maxScroll * 2);
    
    if (positionRef.current < maxScroll) {
      container.scrollTop = positionRef.current;
    } else {
      container.scrollTop = maxScroll * 2 - positionRef.current;
    }
    
    animationRef.current = requestAnimationFrame(animate);
  };

  // Start animation if not already running
  const ensureAnimationIsRunning = () => {
    if (isAnimatingRef.current) return; // Don't restart if already running
    
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
    }
    
    isAnimatingRef.current = true;
    animationRef.current = requestAnimationFrame(animate);
  };

  // Stop animation
  const stopAnimation = () => {
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    }
    isAnimatingRef.current = false;
  };

  // Main effect for controlling animations based on state
  useEffect(() => {
    // If component should animate
    if (isStreaming && !isExpanded && scrollContainerRef.current && cleanedThinkingContent) {
      ensureAnimationIsRunning();
    } else {
      stopAnimation();
    }
    
    // Cleanup
    return () => stopAnimation();
  }, [isStreaming, isExpanded, cleanedThinkingContent]);
  
  // Track content changes without restarting animation
  useEffect(() => {
    // Update our content tracker, but don't restart animation
    lastContentRef.current = cleanedThinkingContent;
  }, [cleanedThinkingContent]);

  // Don't render anything if content is empty
  if (!cleanedThinkingContent.trim()) return null;

  // Determine if we should show the preview section
  const shouldShowPreview = isStreaming && !isExpanded && cleanedThinkingContent.trim().length > 0;
  const hasPreviewContent = getPeekContent().trim().length > 0;

  return (
    <div className="thinking-box">
      <div className={`thinking-box__container ${!isExpanded && "thinking-box__container--collapsed"} ${(!shouldShowPreview || !hasPreviewContent) && "thinking-box__container--no-preview"}`}>
        <div 
          className="thinking-box__header"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <div className="thinking-box__title">
            <TbBrain className="thinking-box__icon" />
            <span className="thinking-box__title-text">
              {isStreaming ? "Thinking" : "Thought for"}
            </span>
            <span className="thinking-box__timer">
              {elapsedTime}s
            </span>
          </div>
          <div className="thinking-box__collapse-icon">
            {isExpanded ? <FiChevronUp size={16} /> : <FiChevronDown size={16} />}
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
                rehypePlugins={[[rehypePrism, { ignoreMissing: true }], rehypeKatex]}
                urlTransform={transformLinkUri}
              >
                {cleanedThinkingContent}
              </ReactMarkdown>
            </div>
          </div>
        ) : (
          shouldShowPreview && hasPreviewContent && (
            <div className="thinking-box__preview">
              <div className="thinking-box__fade-container">
                <div 
                  ref={scrollContainerRef}
                  className="thinking-box__scroll-content"
                >
                  <pre className="thinking-box__preview-text">{getPeekContent()}</pre>
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