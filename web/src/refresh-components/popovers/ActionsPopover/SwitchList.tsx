"use client";

import React, { useMemo, useState } from "react";
import useFocusOnMount from "@opal/hooks/useFocusOnMount";
import {
  Button,
  InputTypeIn,
  LineItemButton,
  PopoverMenu,
  Switch,
  Tooltip,
} from "@opal/components";
import { ContentAction } from "@opal/layouts";
import type { IconProps } from "@opal/types";
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
  const focusOnMount = useFocusOnMount<HTMLInputElement>();
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
            ref={focusOnMount}
          />
        </div>,

        <LineItemButton
          sizePreset="main-ui"
          rounding="sm"
          key="enable-disable-all"
          icon={allDisabled ? SvgPlug : SvgUnplug}
          onClick={allDisabled ? onEnableAll : onDisableAll}
          title={allDisabled ? "Enable All" : "Disable All"}
        />,

        ...filteredItems.map((item) => {
          const tooltip = item.disabled
            ? item.disabledTooltip
            : item.description;
          return (
            <Tooltip key={item.id} tooltip={tooltip}>
              {/* The row does nothing when pressed — the Switch beside it is
                  the control — so it is a label, not a button. Padding matches
                  LineItemButton so it lines up with the rows around it.

                  It takes a tab stop only while disabled. The Switch is a
                  native disabled button then, so it cannot be focused, and the
                  tooltip explaining why would be reachable by pointer alone.
                  Enabled, the Switch carries the focus and the tooltip opens
                  from it, so a stop here would only be a second one. */}
              <div
                className="w-full p-1.5"
                // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- the stop exists so a keyboard can reach the tooltip that says why the row is disabled; its Switch is a disabled button and cannot hold focus
                tabIndex={item.disabled ? 0 : undefined}
              >
                <ContentAction
                  sizePreset="main-ui"
                  padding={0.5}
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
                      disabled={item.disabled}
                    />
                  }
                  title={item.label}
                />
              </div>
            </Tooltip>
          );
        }),
      ]}
    </PopoverMenu>
  );
}
