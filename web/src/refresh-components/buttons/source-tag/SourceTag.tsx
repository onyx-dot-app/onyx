"use client";

import {
  memo,
  useState,
  useMemo,
  useCallback,
  useRef,
  useLayoutEffect,
} from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import { ValidSources } from "@/lib/types";
import SourceTagDetailsCard, {
  SourceInfo,
} from "@/refresh-components/buttons/source-tag/SourceTagDetailsCard";

export type { SourceInfo };

// Variant-specific styles
const sizeClasses = {
  inlineCitation: {
    container: "rounded-04 p-0.5 gap-0.5",
  },
  tag: {
    container: "rounded-08 h-[2.25rem] min-w-[2.25rem] p-2 gap-1",
  },
} as const;

/**
 * Hook to detect if text content is truncated within its container.
 *
 * Compares scrollWidth vs clientWidth to determine if CSS truncation is active.
 * Re-checks on window resize and when the text content changes.
 *
 * @param text - The text content to monitor for truncation
 * @returns Object containing:
 *   - `isTruncated`: Whether the text is currently truncated
 *   - `textRef`: Ref to attach to the text container element
 *
 * @example
 * ```tsx
 * const { isTruncated, textRef } = useIsTruncated(displayName);
 * return (
 *   <span ref={textRef} className="truncate">
 *     {displayName}
 *   </span>
 * );
 * ```
 */
function useIsTruncated(text: string) {
  const [isTruncated, setIsTruncated] = useState(false);
  const textRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    function checkTruncation() {
      if (textRef.current) {
        setIsTruncated(
          textRef.current.scrollWidth > textRef.current.clientWidth
        );
      }
    }

    const timeoutId = setTimeout(checkTruncation, 0);
    window.addEventListener("resize", checkTruncation);

    return () => {
      clearTimeout(timeoutId);
      window.removeEventListener("resize", checkTruncation);
    };
  }, [text]);

  return { isTruncated, textRef };
}

/**
 * Generates a unique key for a source based on its icon type.
 *
 * Used to deduplicate sources with identical icons when displaying stacked icons.
 *
 * @param source - The source info object
 * @returns A unique string key based on:
 *   - Custom icon name if `source.icon` exists
 *   - Hostname from URL for web sources
 *   - Source type string for other sources
 */
const getIconKey = (source: SourceInfo): string => {
  if (source.icon) return source.icon.name || "custom";
  if (source.sourceType === ValidSources.Web && source.sourceUrl) {
    try {
      return new URL(source.sourceUrl).hostname;
    } catch {
      return source.sourceUrl;
    }
  }
  return source.sourceType;
};

/**
 * Renders the appropriate icon for a source based on its type and properties.
 *
 * Icon selection priority:
 * 1. Custom icon component (`source.icon`) - rendered directly
 * 2. Web source with URL - renders favicon via `WebResultIcon`
 * 3. Default - renders standard `SourceIcon` for the source type
 *
 * @param props.source - The source info containing icon, sourceType, and optional sourceUrl
 */
const SourceIconRenderer = ({ source }: { source: SourceInfo }) => {
  if (source.icon) {
    return <source.icon size={12} />;
  }
  if (source.sourceType === ValidSources.Web && source.sourceUrl) {
    return <WebResultIcon url={source.sourceUrl} size={12} />;
  }
  return <SourceIcon sourceType={source.sourceType} iconSize={12} />;
};

/**
 * Props for the IconStack sub-component.
 */
interface IconStackProps {
  sources: SourceInfo[];
  isQuery?: boolean;
  isOpen: boolean;
  showDetailsCard: boolean;
}

/**
 * Renders a horizontal stack of up to 3 source icons with overlapping layout.
 *
 * Icons are displayed with negative spacing to create a stacked/overlapping effect.
 * Each icon has a border that changes color based on open/hover states.
 *
 * @param props.sources - Array of sources to display (max 3 shown)
 * @param props.isQuery - When true, removes icon background
 * @param props.isOpen - Whether the details card is currently open
 * @param props.showDetailsCard - Whether hover interactions are enabled
 */
const IconStack = ({
  sources,
  isQuery,
  isOpen,
  showDetailsCard,
}: IconStackProps) => (
  <div className="flex items-center -space-x-1.5">
    {sources.slice(0, 3).map((source, index) => (
      <div
        key={source.id ?? `source-${index}`}
        className={cn(
          "relative flex items-center justify-center p-0.5 rounded-04",
          !isQuery && "bg-background-tint-00",
          "border transition-colors duration-150",
          isOpen
            ? "border-background-tint-inverted-03"
            : "border-background-tint-02",
          !showDetailsCard &&
            !isQuery &&
            "group-hover:border-background-tint-inverted-03"
        )}
        style={{ zIndex: sources.length - index }}
      >
        <SourceIconRenderer source={source} />
      </div>
    ))}
  </div>
);

/**
 * Shared text styling props passed to Text and Truncated components.
 * Computed based on `inlineCitation` and `isOpen` state.
 */
interface TextStyleProps {
  figureSmallValue?: boolean;
  secondaryBody?: boolean;
  text05?: boolean;
  text03?: boolean;
  text04?: boolean;
  inverted?: boolean;
}

/**
 * Props for the QueryText sub-component.
 */
interface QueryTextProps {
  expanded: boolean;
  displayName: string;
  tooltipText?: string;
  isTruncated: boolean;
  textRef: React.RefObject<HTMLSpanElement | null>;
  textStyleProps: TextStyleProps;
}

/**
 * Renders query text with two display modes based on expansion state.
 *
 * **Collapsed mode** (default):
 * - Text is truncated at 10rem with CSS overflow
 * - Shows tooltip with full text when truncated
 * - Clicking expands to full width
 *
 * **Expanded mode**:
 * - Text displays at full width using `Truncated` component
 * - Provides its own overflow handling with tooltip
 *
 * @param props.expanded - Whether text is in expanded (full-width) mode
 * @param props.displayName - The text content to display
 * @param props.tooltipText - Custom tooltip text (defaults to displayName)
 * @param props.isTruncated - Whether the collapsed text is currently truncated
 * @param props.textRef - Ref for measuring text truncation in collapsed mode
 * @param props.textStyleProps - Shared text styling props (colors, typography)
 */
const QueryText = ({
  expanded,
  displayName,
  tooltipText,
  isTruncated,
  textRef,
  textStyleProps,
}: QueryTextProps) => {
  if (expanded) {
    return (
      <Truncated
        {...textStyleProps}
        className="max-w-full transition-colors duration-150"
      >
        {displayName}
      </Truncated>
    );
  }

  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span ref={textRef} className="max-w-[10rem] truncate block">
            <Text
              as="span"
              {...textStyleProps}
              className="transition-colors duration-150"
            >
              {displayName}
            </Text>
          </span>
        </TooltipTrigger>
        {isTruncated && (
          <TooltipContent
            side="top"
            className="max-w-[400px] break-words whitespace-normal"
          >
            <Text as="p" textLight05>
              {tooltipText ?? displayName}
            </Text>
          </TooltipContent>
        )}
      </Tooltip>
    </TooltipProvider>
  );
};

/**
 * Props for the SourceTag component.
 */
export interface SourceTagProps {
  /** Use inline citation size (smaller, for use within text) */
  inlineCitation?: boolean;

  /** Display name shown on the tag (e.g., "Google Drive", "Business Insider") */
  displayName: string;

  /** URL to display below name (for site type - shows domain) */
  displayUrl?: string;

  /** Array of sources for navigation in details card */
  sources: SourceInfo[];

  /** Callback when a source is clicked in the details card */
  onSourceClick?: () => void;

  /** Whether to show the details card on hover (defaults to true) */
  showDetailsCard?: boolean;

  /** Additional CSS classes */
  className?: string;

  /** When true, removes icon background and wraps displayName with Truncated */
  isQuery?: boolean;

  /** When true, hides icon, removes background, shows bg-background-tint-02 on hover */
  isMore?: boolean;

  /** When true, no details card, no background, tint-02 on hover */
  toggleSource?: boolean;

  /** Tooltip text shown when query is truncated (defaults to displayName) */
  tooltipText?: string;
}

/**
 * A tag component for displaying source citations with multiple display modes.
 *
 * ## Display Modes
 *
 * **Standard Tag** (default):
 * - Shows stacked source icons + display name
 * - Hovering opens a details card with source navigation
 *
 * **Inline Citation** (`inlineCitation`):
 * - Compact size for use within text content
 * - Shows "+N" count for multiple sources
 *
 * **Query Mode** (`isQuery`):
 * - No icon background, text-only appearance
 * - Truncated text expands on click
 * - Shows tooltip when truncated
 *
 * **More Mode** (`isMore`):
 * - Hides icons, shows only text
 * - No default background, shows tint on hover
 *
 * **Toggle Source** (`toggleSource`):
 * - No details card on hover
 * - No default background, shows tint on hover
 *
 * @example
 * ```tsx
 * // Standard tag with details card
 * <SourceTag
 *   displayName="Google Drive"
 *   sources={[{ sourceType: ValidSources.GoogleDrive, ... }]}
 * />
 *
 * // Inline citation within text
 * <SourceTag
 *   inlineCitation
 *   displayName="Source 1"
 *   sources={multipleSources}
 * />
 *
 * // Query mode for search queries
 * <SourceTag
 *   isQuery
 *   displayName="What is the meaning of life?"
 *   sources={[]}
 * />
 * ```
 */
const SourceTagInner = ({
  inlineCitation,
  displayName,
  displayUrl,
  sources,
  onSourceClick,
  showDetailsCard = true,
  className,
  isQuery,
  isMore,
  toggleSource,
  tooltipText,
}: SourceTagProps) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const { isTruncated, textRef } = useIsTruncated(displayName);

  const uniqueSources = useMemo(
    () =>
      sources.filter(
        (source, index, arr) =>
          arr.findIndex((s) => getIconKey(s) === getIconKey(source)) === index
      ),
    [sources]
  );

  const extraCount = sources.length - 1;

  const size = inlineCitation ? "inlineCitation" : "tag";
  const styles = sizeClasses[size];

  // Shared text styling props
  const textStyleProps = useMemo<TextStyleProps>(
    () => ({
      figureSmallValue: inlineCitation,
      secondaryBody: !inlineCitation,
      text05: isOpen,
      text03: !isOpen && inlineCitation,
      text04: !isOpen && !inlineCitation,
      inverted: isOpen,
    }),
    [inlineCitation, isOpen]
  );

  // Cursor class based on mode and state
  const cursorClass = useMemo(() => {
    if (!isQuery) return "cursor-pointer";
    if (!isTruncated || expanded) return "cursor-default";
    return "cursor-pointer";
  }, [isQuery, isTruncated, expanded]);

  // Background class based on mode and state
  const backgroundClass = useMemo(() => {
    if (isOpen) return "bg-background-tint-inverted-03";
    if (isMore || toggleSource) return "hover:bg-background-tint-02";
    if (!showDetailsCard && !isQuery)
      return "bg-background-tint-02 hover:bg-background-tint-inverted-03";
    return "bg-background-tint-02";
  }, [isOpen, isMore, toggleSource, showDetailsCard, isQuery]);

  const handlePrev = useCallback(() => {
    setCurrentIndex((prev) => Math.max(0, prev - 1));
  }, []);

  const handleNext = useCallback(() => {
    setCurrentIndex((prev) => Math.min(sources.length - 1, prev + 1));
  }, [sources.length]);

  // Reset to first source when tooltip closes
  const handleOpenChange = useCallback((open: boolean) => {
    setIsOpen(open);
    if (!open) {
      setCurrentIndex(0);
    }
  }, []);

  const handleClick = useCallback(() => {
    // Only expand if truncated
    if (isQuery && !expanded && isTruncated) {
      setExpanded(true);
    }
    onSourceClick?.();
  }, [isQuery, expanded, isTruncated, onSourceClick]);

  const buttonContent = (
    <button
      type="button"
      className={cn(
        "group inline-flex items-center transition-all duration-150",
        "appearance-none border-none",
        backgroundClass,
        styles.container,
        isQuery && "gap-0",
        isQuery && expanded && "w-fit",
        cursorClass,
        className
      )}
      onClick={handleClick}
    >
      {/* Stacked icons container - only for tag variant */}
      {!inlineCitation && !isMore && (
        <IconStack
          sources={uniqueSources}
          isQuery={isQuery}
          isOpen={isOpen}
          showDetailsCard={showDetailsCard}
        />
      )}

      <div
        className={cn(
          "flex items-baseline",
          !inlineCitation && "pr-0.5",
          isQuery && expanded && "w-fit"
        )}
      >
        {isQuery ? (
          <QueryText
            expanded={expanded}
            displayName={displayName}
            tooltipText={tooltipText}
            isTruncated={isTruncated}
            textRef={textRef}
            textStyleProps={textStyleProps}
          />
        ) : (
          <Text
            {...textStyleProps}
            className={cn(
              "max-w-[10rem] truncate transition-colors duration-150",
              !showDetailsCard &&
                !isQuery &&
                "group-hover:text-text-inverted-05"
            )}
          >
            {displayName}
          </Text>
        )}

        {/* Count - for inline citation */}
        {inlineCitation && sources.length > 1 && (
          <Text
            figureSmallValue
            text05={isOpen}
            text03={!isOpen}
            inverted={isOpen}
            className={cn(
              "transition-colors duration-150",
              !showDetailsCard &&
                !isQuery &&
                "group-hover:text-text-inverted-05"
            )}
          >
            +{extraCount}
          </Text>
        )}

        {/* URL - for tag variant */}
        {!inlineCitation && displayUrl && (
          <Text
            figureSmallValue
            text05={isOpen}
            text02={!isOpen}
            inverted={isOpen}
            className={cn(
              "max-w-[10rem] truncate transition-colors duration-150",
              !showDetailsCard &&
                !isQuery &&
                "group-hover:text-text-inverted-05"
            )}
          >
            {displayUrl}
          </Text>
        )}
      </div>
    </button>
  );

  if (!showDetailsCard || toggleSource) {
    return buttonContent;
  }

  return (
    <TooltipProvider delayDuration={50}>
      <Tooltip open={isOpen} onOpenChange={handleOpenChange}>
        <TooltipTrigger asChild>{buttonContent}</TooltipTrigger>
        <TooltipContent
          side="bottom"
          align="start"
          sideOffset={4}
          className="bg-transparent p-0 shadow-none border-none"
        >
          <SourceTagDetailsCard
            sources={sources}
            currentIndex={currentIndex}
            onPrev={handlePrev}
            onNext={handleNext}
          />
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

/**
 * Memoized SourceTag component for displaying source citations.
 *
 * @see {@link SourceTagInner} for full documentation and examples.
 */
const SourceTag = memo(SourceTagInner);
export default SourceTag;
