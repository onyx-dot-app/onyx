"use client";

import { memo, useState, useMemo, useCallback } from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
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
    container: "rounded-08 p-1 gap-1",
  },
} as const;

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
}

const SourceTagInner = ({
  inlineCitation,
  displayName,
  displayUrl,
  sources,
  onSourceClick,
  showDetailsCard = true,
  className,
}: SourceTagProps) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isOpen, setIsOpen] = useState(false);

  const uniqueSources = useMemo(
    () =>
      sources.filter(
        (source, index, arr) =>
          arr.findIndex((s) => getIconKey(s) === getIconKey(source)) === index
      ),
    [sources]
  );

  const showCount = sources.length > 1;
  const extraCount = sources.length - 1;

  const size = inlineCitation ? "inlineCitation" : "tag";
  const styles = sizeClasses[size];

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

  const buttonContent = (
    <button
      type="button"
      className={cn(
        "group inline-flex items-center cursor-pointer transition-all duration-150",
        "appearance-none border-none bg-background-tint-02",
        isOpen && "bg-background-tint-inverted-03",
        !showDetailsCard && "hover:bg-background-tint-inverted-03",
        styles.container,
        className
      )}
      onClick={() => onSourceClick?.()}
    >
      {/* Stacked icons container - only for tag variant */}
      {!inlineCitation && (
        <div className="flex items-center -space-x-1.5">
          {uniqueSources.slice(0, 3).map((source, index) => (
            <div
              key={source.id}
              className={cn(
                "relative flex items-center justify-center p-0.5 rounded-04",
                "bg-background-tint-00 border transition-colors duration-150",
                isOpen
                  ? "border-background-tint-inverted-03"
                  : "border-background-tint-02",
                !showDetailsCard &&
                  "group-hover:border-background-tint-inverted-03"
              )}
              style={{ zIndex: uniqueSources.slice(0, 3).length - index }}
            >
              {source.icon ? (
                <source.icon size={12} />
              ) : source.sourceType === ValidSources.Web && source.sourceUrl ? (
                <WebResultIcon url={source.sourceUrl} size={12} />
              ) : (
                <SourceIcon
                  sourceType={
                    source.sourceType === ValidSources.Web
                      ? ValidSources.Web
                      : source.sourceType
                  }
                  iconSize={12}
                />
              )}
            </div>
          ))}
        </div>
      )}

      <div className={cn("flex items-baseline", !inlineCitation && "pr-0.5")}>
        <Text
          figureSmallValue={inlineCitation && !isOpen}
          figureSmallLabel={inlineCitation && isOpen}
          secondaryBody={!inlineCitation}
          text05={isOpen}
          text03={!isOpen && inlineCitation}
          text04={!isOpen && !inlineCitation}
          inverted={isOpen}
          className={cn(
            "max-w-[10rem] truncate transition-colors duration-150",
            !showDetailsCard && "group-hover:text-text-inverted-05"
          )}
        >
          {displayName}
        </Text>

        {/* Count - for inline citation */}
        {inlineCitation && showCount && (
          <Text
            figureSmallValue
            text05={isOpen}
            text03={!isOpen}
            inverted={isOpen}
            className={cn(
              "transition-colors duration-150",
              !showDetailsCard && "group-hover:text-text-inverted-05"
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
              !showDetailsCard && "group-hover:text-text-inverted-05"
            )}
          >
            {displayUrl}
          </Text>
        )}
      </div>
    </button>
  );

  if (!showDetailsCard) {
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

const SourceTag = memo(SourceTagInner);
export default SourceTag;
