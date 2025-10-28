"use client";

import React, { useMemo, useRef, useState } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import Text from "@/refresh-components/texts/Text";
import { Toggle } from "@/components/ui/toggle";
import { cn } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgChevronLeft from "@/icons/chevron-left";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Button from "@/refresh-components/buttons/Button";
import SvgPlug from "@/icons/plug";
import SvgUnplug from "@/icons/unplug";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";

export interface ToggleListItem {
  id: string;
  label: string;
  description?: string;
  leading?: React.ReactNode;
  isEnabled: boolean;
  onToggle: () => void;
}

interface ToggleListProps {
  items: ToggleListItem[];
  searchPlaceholder: string;
  allDisabled: boolean;
  onDisableAll: () => void;
  onEnableAll: () => void;
  disableAllLabel: string;
  enableAllLabel: string;
  noResultsText: string;
  noItemsText: string;
  onBack: () => void;
  onScrollStateChange: (element: HTMLElement) => void;
  showTopShadow: boolean;
  showFadeMask: boolean;
  footer?: React.ReactNode;
}

export function ToggleList({
  items,
  searchPlaceholder,
  allDisabled,
  onDisableAll,
  onEnableAll,
  disableAllLabel,
  enableAllLabel,
  noResultsText,
  noItemsText,
  onBack,
  onScrollStateChange,
  showTopShadow,
  showFadeMask,
  footer,
}: ToggleListProps) {
  const [searchTerm, setSearchTerm] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const filteredItems = useMemo(() => {
    if (!searchTerm) return items;
    const searchLower = searchTerm.toLowerCase();
    return items.filter((item) => {
      return (
        item.label.toLowerCase().includes(searchLower) ||
        (item.description &&
          item.description.toLowerCase().includes(searchLower))
      );
    });
  }, [items, searchTerm]);

  const toggleAllLabel = allDisabled ? enableAllLabel : disableAllLabel;
  const toggleAllHandler = allDisabled ? onEnableAll : onDisableAll;
  const ToggleAllIcon = allDisabled ? SvgPlug : SvgUnplug;

  return (
    <div className="flex flex-col overflow-hidden">
      <div className="bg-transparent flex-shrink-0">
        <div className="mx-1">
          <div className="flex items-center gap-1">
            <IconButton
              icon={SvgChevronLeft}
              // TODO: Confirm IconButton variant
              internal
              aria-label="Back"
              onClick={() => {
                setSearchTerm("");
                onBack();
              }}
            />
            <InputTypeIn
              internal
              placeholder={searchPlaceholder}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              autoFocus
              className="flex-1"
            />
          </div>
        </div>
        <div className="mx-1">
          <Button
            defaulted
            tertiary
            type="button"
            includeLeftSpacer={false}
            className="mt-1 w-full justify-between"
            rightIcon={ToggleAllIcon}
            onClick={toggleAllHandler}
          >
            {toggleAllLabel}
          </Button>
        </div>
        <div className="border-b border-border mx-1 mt-1" />
        {/* TODO: Use VerticalShadowScroller */}
        <div
          className="mx-1 h-2 -mb-2 transition-opacity ease-out"
          style={{
            background:
              "linear-gradient(to bottom, rgba(0, 0, 0, 0.06), transparent)",
            opacity: showTopShadow ? 1 : 0,
          }}
        />
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto min-h-0 relative"
        onScroll={(e) => onScrollStateChange(e.currentTarget)}
      >
        <div className="space-y-1.5 pt-2 pb-2">
          {filteredItems.length === 0 ? (
            <Text className="text-center py-4 text-text-02">
              {items.length === 0 ? noItemsText : noResultsText}
            </Text>
          ) : (
            filteredItems.map((item) => {
              const content = item.leading ? (
                <div className="flex items-center gap-3">
                  <div className="flex-shrink-0">{item.leading}</div>
                  <div className="flex flex-col cursor-default">
                    <Text
                      className={cn(
                        "text-sm font-medium",
                        item.isEnabled ? "text-text-04" : "text-text-02"
                      )}
                    >
                      {item.label}
                    </Text>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col cursor-default">
                  <Text
                    className={cn(
                      "text-sm font-medium",
                      item.isEnabled ? "text-text-04" : "text-text-02"
                    )}
                  >
                    {item.label}
                  </Text>
                </div>
              );

              const labelNode = item.description ? (
                <SimpleTooltip
                  tooltip={item.description}
                  side="right"
                  align="start"
                  className="max-w-xs"
                >
                  {content}
                </SimpleTooltip>
              ) : (
                content
              );

              return (
                <div
                  key={item.id}
                  className="flex items-center justify-between px-2 py-1.5 mx-1 rounded-lg hover:bg-background-neutral-01 transition-colors"
                >
                  {labelNode}
                  <Toggle
                    isEnabled={item.isEnabled}
                    onClick={item.onToggle}
                    ariaLabel={`Toggle ${item.label}`}
                    className=""
                    enabledClassName="bg-action-link-05"
                    disabledClassName="bg-background-tint-03"
                    thumbBaseClassName="top-[2px] left-[2px] h-[12px] w-[12px] rounded-full"
                    enabledThumbClassName="translate-x-[12px] bg-background-neutral-light-00"
                    disabledThumbClassName="translate-x-0 bg-background-neutral-light-00"
                    style={{
                      width: "28px",
                      height: "16px",
                      borderRadius: "var(--Radius-Round, 1000px)",
                    }}
                    thumbStyle={{
                      boxShadow: "0 0 1px 1px rgba(0, 0, 0, 0.05)",
                    }}
                  />
                </div>
              );
            })
          )}
        </div>
        <div
          className="sticky w-full pointer-events-none transition-opacity ease-out bg-gradient-to-t from-background-neutral-00 to-transparent"
          style={{
            bottom: footer ? "40px" : "0px",
            height: "40px",
            opacity: showFadeMask ? 1 : 0,
          }}
        />
        {footer}
      </div>
    </div>
  );
}
