"use client";

import type { ReactNode } from "react";
import { Button, InputTypeIn, Text, Tooltip } from "@opal/components";
import { SvgRevert } from "@opal/icons";
import { IconLoader } from "@opal/loaders";

interface PanelUrlBarProps {
  // The path or URL shown, left to right, when the bar has no search
  displayUrl?: string;
  // With `onSearchChange`, the bar is a search field in place of the location
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  placeholder?: string;
  // The reload button; without it, the bar has none
  refresh?: {
    label: string;
    onRefresh?: () => void;
    isRefreshing: boolean;
    isUserRefreshing: boolean;
  };
  // Actions after the location or search field
  children?: ReactNode;
}

/** The row under an output panel's tabs: the location or a search field. */
export function PanelUrlBar({
  displayUrl,
  searchValue,
  onSearchChange,
  placeholder,
  refresh,
  children,
}: PanelUrlBarProps) {
  return (
    <div className="flex h-11 shrink-0 items-center gap-2 px-3 pb-2">
      {refresh && (
        <Button
          icon={refresh.isUserRefreshing ? IconLoader : SvgRevert}
          prominence="tertiary"
          size="sm"
          disabled={
            !refresh.onRefresh ||
            refresh.isRefreshing ||
            refresh.isUserRefreshing
          }
          onClick={refresh.onRefresh}
          tooltip={refresh.label}
          aria-label={refresh.label}
          aria-busy={refresh.isRefreshing || refresh.isUserRefreshing}
        />
      )}
      <div
        data-testid="url-bar-pill"
        className="flex h-8 min-w-0 flex-1 items-center rounded-md bg-background-tint-02 px-2 overflow-hidden"
      >
        {onSearchChange ? (
          <InputTypeIn
            variant="internal"
            icon="search"
            value={searchValue ?? ""}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={placeholder}
            aria-label={placeholder}
          />
        ) : (
          displayUrl !== undefined && (
            <Tooltip tooltip={displayUrl} side="bottom">
              <div className="min-w-0 flex-1" data-testid="url-text-wrapper">
                <Text
                  as="p"
                  dir="ltr"
                  font="secondary-body"
                  color="text-03"
                  maxLines={1}
                >
                  {displayUrl}
                </Text>
              </div>
            </Tooltip>
          )
        )}
      </div>
      {children}
    </div>
  );
}
