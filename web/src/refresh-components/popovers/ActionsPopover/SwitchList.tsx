"use client";

import React, { useMemo, useState } from "react";
import IconButton from "@/refresh-components/buttons/IconButton";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { PopoverMenu } from "@/components/ui/popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import type { IconProps } from "@opal";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Switch from "@/refresh-components/inputs/Switch";
import { SvgChevronLeft, SvgPlug, SvgUnplug } from "@opal/icons";

export interface SwitchListItem {
  id: string;
  label: string;
  description?: string;
  leading?: React.ReactNode;
  isEnabled: boolean;
  onToggle: () => void;
}

export interface SwitchListProps {
  items: SwitchListItem[];
  searchPlaceholder: string;
  allDisabled: boolean;
  onDisableAll: () => void;
  onEnableAll: () => void;
  disableAllLabel: string;
  enableAllLabel: string;
  onBack: () => void;
  footer?: React.ReactNode;
}

export default function SwitchList({
  items,
  searchPlaceholder,
  allDisabled,
  onDisableAll,
  onEnableAll,
  onBack,
  footer,
}: SwitchListProps) {
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
                        item.leading) as React.FunctionComponent<IconProps>)
                    : undefined
                }
                rightChildren={
                  <Switch
                    checked={item.isEnabled}
                    onCheckedChange={item.onToggle}
                    aria-label={`Toggle ${item.label}`}
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
