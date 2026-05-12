"use client";

import React, { useMemo, useState } from "react";
import { Button, LineItemButton } from "@opal/components";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { PopoverMenu } from "@opal/components";
import type { IconProps } from "@opal/types";
import Switch from "@/refresh-components/inputs/Switch";
import { SvgChevronLeft, SvgPlug, SvgUnplug } from "@opal/icons";

export interface SwitchListItem {
  id: string;
  label: string;
  description?: string;
  leading?: React.ReactNode;
  isEnabled: boolean;
  onToggle: () => void;
  disabled?: boolean;
  disabledTooltip?: string;
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
    <PopoverMenu footer={footer}>
      {[
        <div className="flex items-center gap-1" key="search">
          <Button
            icon={SvgChevronLeft}
            prominence="tertiary"
            size="sm"
            aria-label="Back"
            onClick={() => {
              setSearchTerm("");
              onBack();
            }}
          />
          <InputTypeIn
            variant="internal"
            placeholder={searchPlaceholder}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            autoFocus
          />
        </div>,

        <LineItemButton
          key="enable-disable-all"
          sizePreset="main-ui"
          variant="section"
          rounding="sm"
          center
          icon={allDisabled ? SvgPlug : SvgUnplug}
          onClick={allDisabled ? onEnableAll : onDisableAll}
          title={allDisabled ? "Enable All" : "Disable All"}
        />,

        ...filteredItems.map((item) => {
          const tooltip = item.disabled
            ? item.disabledTooltip
            : item.description;
          return (
            <LineItemButton
              key={item.id}
              sizePreset="main-ui"
              variant="section"
              rounding="sm"
              center
              tooltip={tooltip}
              tooltipSide="right"
              icon={
                item.leading
                  ? ((() => item.leading) as React.FunctionComponent<IconProps>)
                  : undefined
              }
              title={item.label}
              rightChildren={
                <Switch
                  checked={item.isEnabled}
                  onCheckedChange={item.onToggle}
                  aria-label={`Toggle ${item.label}`}
                  disabled={item.disabled}
                />
              }
            />
          );
        }),
      ]}
    </PopoverMenu>
  );
}
