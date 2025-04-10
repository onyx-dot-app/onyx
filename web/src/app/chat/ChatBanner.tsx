"use client";

import { SettingsContext } from "@/components/settings/SettingsProvider";
import { useContext, useState, useRef, useLayoutEffect } from "react";
import { ChevronDownIcon } from "@/components/icons/icons";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";

export function ChatBanner() {
  const settings = useContext(SettingsContext);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  const contentRef = useRef<HTMLDivElement>(null);
  const fullContentRef = useRef<HTMLDivElement>(null);

  // Check for text overflow
  useLayoutEffect(() => {
    const checkOverflow = () => {
      if (contentRef.current && fullContentRef.current) {
        const contentRect = contentRef.current.getBoundingClientRect();
        const fullContentRect = fullContentRef.current.getBoundingClientRect();

        const isWidthOverflowing = fullContentRect.width > contentRect.width;
        const isHeightOverflowing = fullContentRect.height > contentRect.height;

        setIsOverflowing(isWidthOverflowing || isHeightOverflowing);
      }
    };

    checkOverflow();
    window.addEventListener("resize", checkOverflow);
    return () => window.removeEventListener("resize", checkOverflow);
  }, []);

  // Bail out if no custom header content
  if (!settings?.enterpriseSettings?.custom_header_content) {
    return null;
  }

  const handleMouseEnter = () => setIsExpanded(true);
  const handleMouseLeave = () => setIsExpanded(false);

  return (
    <div
      className={`
        z-[39]
        w-full
        mx-auto
        relative
        cursor-default
        shadow-sm
        rounded
        border
        border-border
        border-l-8 border-l-400
        border-r-4 border-r-200
        bg-background-sidebar
        transition-all duration-300 ease-in-out
        ${isExpanded ? "shadow-md bg-background-100" : ""}
      `}
      onMouseLeave={handleMouseLeave}
      aria-expanded={isExpanded}
    >
      <div className="text-text-darker text-sm w-full">
        {/* Padding for consistent spacing */}
        <div className="relative p-2">
          {/* Collapsible container */}
          <div
            className={`
              overflow-hidden
              transition-all duration-300 ease-in-out
              ${
                isExpanded
                  ? "max-h-[1000px]"
                  : settings.enterpriseSettings.two_lines_for_chat_header
                    ? "max-h-[3em]" // ~3 lines
                    : "max-h-[1.5em]" // ~1.5 lines
              }
            `}
          >
            {/* Visible content container */}
            <div ref={contentRef} className="text-center max-w-full">
              <MinimalMarkdown
                // Ensure text can wrap to multiple lines
                className="prose text-left text-sm max-w-full whitespace-normal break-words"
                content={settings.enterpriseSettings.custom_header_content}
              />
            </div>
          </div>

          {/* Invisible element to measure overflow */}
          <div className="absolute top-0 left-0 invisible">
            <div
              ref={fullContentRef}
              className="overflow-hidden invisible text-center max-w-full"
            >
              <MinimalMarkdown
                // Same wrapping behavior as visible content
                className="prose text-sm max-w-full whitespace-normal break-words"
                content={settings.enterpriseSettings.custom_header_content}
              />
            </div>
          </div>

          {/* Chevron button if content is truncated */}
        </div>
      </div>
      <div className="absolute -top-1 right-0">
        {isOverflowing && !isExpanded && (
          <button
            onMouseEnter={handleMouseEnter}
            className="cursor-pointer bg-background-100 p-.5 rounded-full transition-opacity duration-300 ease-in-out"
            aria-label="Expand banner content"
            onClick={() => setIsExpanded(true)}
          >
            <ChevronDownIcon className="h-3 w-3 text-text-darker" />
          </button>
        )}
      </div>
    </div>
  );
}
