"use client";

import React, { useMemo, useState } from "react";
import { Toggle } from "@/components/ui/toggle";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgChevronLeft from "@/icons/chevron-left";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import SvgPlug from "@/icons/plug";
import SvgUnplug from "@/icons/unplug";
import { PopoverMenu } from "@/components/ui/popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import { SvgProps } from "@/icons";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";

export interface ToggleListItem {
  id: string;
  label: string;
  description?: string;
  leading?: React.ReactNode;
  isEnabled: boolean;
  onToggle: () => void;
}

export interface ToggleListProps {
  items: ToggleListItem[];
  searchPlaceholder: string;
  allDisabled: boolean;
  onDisableAll: () => void;
  onEnableAll: () => void;
  disableAllLabel: string;
  enableAllLabel: string;
  onBack: () => void;
  footer?: React.ReactNode;
}

export default function ToggleList({
  items,
  searchPlaceholder,
  allDisabled,
  onDisableAll,
  onEnableAll,
  onBack,
  footer,
}: ToggleListProps) {
  const [searchTerm, setSearchTerm] = useState("");
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

  return (
    <PopoverMenu medium footer={footer}>
      {[
        <div className="flex items-center gap-1" key="search">
          <IconButton
            icon={SvgChevronLeft}
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
          />
        </div>,

        <LineItem
          key="enable-disable-all"
          icon={allDisabled ? SvgPlug : SvgUnplug}
          type="button"
          onClick={allDisabled ? onEnableAll : onDisableAll}
        >
          {allDisabled ? "Enable All" : "Disable All"}
        </LineItem>,

        ...filteredItems.map((item) => {
          return (
            <SimpleTooltip
              key={item.id}
              tooltip={item.description}
              className="max-w-[30rem]"
            >
              <LineItem
                icon={
                  item.leading
                    ? ((() =>
                        item.leading) as React.FunctionComponent<SvgProps>)
                    : undefined
                }
                rightChildren={
                  <Toggle
                    isEnabled={item.isEnabled}
                    onClick={item.onToggle}
                    ariaLabel={`Toggle ${item.label}`}
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
                }
              >
                {item.label}
              </LineItem>
            </SimpleTooltip>
          );
        }),
      ]}
    </PopoverMenu>
  );
}
