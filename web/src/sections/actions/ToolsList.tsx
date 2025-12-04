"use client";

import React, { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgEye from "@/icons/eye";
import ToolItemSkeleton from "@/sections/actions/skeleton/ToolItemSkeleton";

interface ToolsListProps {
  // Loading state
  isFetching?: boolean;
  onRetry?: () => void;

  // Tool count for footer
  totalCount?: number;
  enabledCount?: number;
  showOnlyEnabled?: boolean;
  onToggleShowOnlyEnabled?: () => void;

  // Empty state
  isEmpty?: boolean;
  searchQuery?: string;
  emptyMessage?: string;
  emptySearchMessage?: string;

  // Content
  children?: React.ReactNode;

  // Styling
  className?: string;
}

const ToolsList: React.FC<ToolsListProps> = ({
  isFetching = false,
  onRetry,
  totalCount,
  enabledCount,
  showOnlyEnabled = false,
  onToggleShowOnlyEnabled,
  isEmpty = false,
  searchQuery,
  emptyMessage = "No tools available",
  emptySearchMessage = "No tools found",
  children,
  className,
}) => {
  const hasRetried = useRef(false);

  useEffect(() => {
    // If the server reports tools but none were returned, try one automatic refetch
    if (!isFetching && isEmpty && !hasRetried.current && onRetry) {
      hasRetried.current = true;
      onRetry();
    }
  }, [isFetching, isEmpty, onRetry]);

  const showFooter =
    totalCount !== undefined && enabledCount !== undefined && totalCount > 0;

  return (
    <>
      <div
        className={cn(
          "flex flex-col gap-1 items-start max-h-[480px] overflow-y-auto w-full",
          className
        )}
      >
        {isFetching ? (
          // Show 5 skeleton items while loading
          <>
            {[...Array(5)].map((_, index) => (
              <ToolItemSkeleton key={`skeleton-${index}`} />
            ))}
          </>
        ) : isEmpty ? (
          // Empty state
          <div className="flex items-center justify-center w-full py-8">
            <Text text03 mainUiBody>
              {searchQuery ? emptySearchMessage : emptyMessage}
            </Text>
          </div>
        ) : (
          // Render children (actual tool items)
          children
        )}
      </div>

      {/* Footer showing enabled tool count with filter toggle */}
      {showFooter && !isEmpty && !isFetching && (
        <div className="relative w-full">
          {/* Gradient fade overlay */}
          <div className="absolute inset-x-0 -top-8 h-8 bg-gradient-to-b from-transparent to-background pointer-events-none" />

          <div className="flex items-center justify-end w-full pt-2 px-2">
            <div className="flex items-center gap-1">
              <Text mainUiBody className="text-action-link-05">
                {enabledCount}
              </Text>
              <Text text03 mainUiBody>
                of {totalCount} tool{totalCount !== 1 ? "s" : ""} enabled
              </Text>
              {onToggleShowOnlyEnabled && (
                <IconButton
                  icon={SvgEye}
                  internal
                  onClick={onToggleShowOnlyEnabled}
                  className={showOnlyEnabled ? "bg-background-tint-02" : ""}
                  tooltip={
                    showOnlyEnabled ? "Show all tools" : "Show only enabled"
                  }
                  aria-label={
                    showOnlyEnabled
                      ? "Show all tools"
                      : "Show only enabled tools"
                  }
                />
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
};

ToolsList.displayName = "ToolsList";
export default ToolsList;
