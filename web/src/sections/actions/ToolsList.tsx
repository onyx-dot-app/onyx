"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { cn } from "@opal/utils";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
import FadingEdgeContainer from "@/refresh-components/FadingEdgeContainer";
import ToolItemSkeleton from "@/sections/actions/skeleton/ToolItemSkeleton";
import EnabledCount from "@/refresh-components/EnabledCount";
import { SvgEye, SvgXCircle } from "@opal/icons";

export interface ToolsListProps {
  // Loading state
  isFetching?: boolean;

  // Tool count for footer
  totalCount?: number;
  enabledCount?: number;
  showOnlyEnabled?: boolean;
  onToggleShowOnlyEnabled?: () => void;
  onUpdateToolsStatus?: (enabled: boolean) => void;

  // Empty state of filtered tools
  isEmpty?: boolean;
  searchQuery?: string;
  emptyMessage?: string;
  emptySearchMessage?: string;

  // Content
  children?: React.ReactNode;

  // Left action (for refresh button and last verified text)
  leftAction?: React.ReactNode;

  // Styling
  className?: string;
}

const ToolsList: React.FC<ToolsListProps> = ({
  isFetching = false,
  totalCount,
  enabledCount = 0,
  showOnlyEnabled = false,
  onToggleShowOnlyEnabled,
  onUpdateToolsStatus,
  isEmpty = false,
  searchQuery,
  emptyMessage,
  emptySearchMessage,
  children,
  leftAction,
  className,
}) => {
  const t = useTranslations("actions");

  const showFooter =
    totalCount !== undefined && enabledCount !== undefined && totalCount > 0;

  return (
    <>
      <FadingEdgeContainer
        direction="bottom"
        className={cn(
          "flex flex-col gap-1 items-start max-h-[30vh] overflow-y-auto",
          className
        )}
      >
        {isFetching ? (
          Array.from({ length: 5 }).map((_, index) => (
            <ToolItemSkeleton key={`skeleton-${index}`} />
          ))
        ) : isEmpty ? (
          <div className="flex items-center justify-center w-full py-8">
            <Text as="p" text03 mainUiBody>
              {searchQuery
                ? (emptySearchMessage ?? t("toolsList.empty.searchMessage"))
                : (emptyMessage ?? t("toolsList.empty.message"))}
            </Text>
          </div>
        ) : (
          children
        )}
      </FadingEdgeContainer>

      {/* Footer showing enabled tool count with filter toggle */}
      {showFooter && !(totalCount === 0) && !isFetching && (
        <div className="pt-2 px-2">
          <div className="flex items-center justify-between gap-2 w-full">
            {/* Left action area */}
            {leftAction}

            {/* Right action area */}
            <div className="flex items-center gap-1 ml-auto">
              {enabledCount > 0 && (
                <EnabledCount
                  enabledCount={enabledCount}
                  totalCount={totalCount}
                  name="tool"
                />
              )}
              {onToggleShowOnlyEnabled && enabledCount > 0 && (
                <Button
                  icon={SvgEye}
                  prominence="tertiary"
                  size="sm"
                  onClick={onToggleShowOnlyEnabled}
                  interaction={showOnlyEnabled ? "hover" : "rest"}
                  tooltip={
                    showOnlyEnabled
                      ? t("toolsList.showAllButton.tooltip")
                      : t("toolsList.showEnabledButton.tooltip")
                  }
                  aria-label={
                    showOnlyEnabled
                      ? t("toolsList.showAllButton.ariaLabel")
                      : t("toolsList.showEnabledButton.ariaLabel")
                  }
                />
              )}
              {onUpdateToolsStatus && enabledCount > 0 && (
                <Button
                  icon={SvgXCircle}
                  prominence="tertiary"
                  size="sm"
                  onClick={() => onUpdateToolsStatus(false)}
                  tooltip={t("toolsList.disableAllButton.tooltip")}
                  aria-label={t("toolsList.disableAllButton.ariaLabel")}
                />
              )}
              {onUpdateToolsStatus && enabledCount === 0 && (
                <Button
                  prominence="tertiary"
                  onClick={() => onUpdateToolsStatus(true)}
                >
                  {t("toolsList.enableAllButton.label")}
                </Button>
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
