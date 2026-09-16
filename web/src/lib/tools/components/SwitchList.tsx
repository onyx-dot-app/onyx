"use client";

import React, { useId, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useFocusOnMount } from "@opal/hooks";
import {
  Button,
  InputTypeIn,
  LineItemButton,
  PopoverMenu,
  InputSwitch,
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
  disableAllLabel,
  enableAllLabel,
  onBack,
  footer,
}: SwitchListProps) {
  const t = useTranslations("actions");
  const listId = useId();
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
            prominence="internal"
            size="sm"
            aria-label={t("switchList.back.ariaLabel")}
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
          rounding={2}
          key="enable-disable-all"
          icon={allDisabled ? SvgPlug : SvgUnplug}
          onClick={allDisabled ? onEnableAll : onDisableAll}
          title={allDisabled ? enableAllLabel : disableAllLabel}
        />,

        ...filteredItems.map((item) => {
          const tooltip = item.disabled
            ? item.disabledTooltip
            : item.description;
          return (
            <Tooltip key={item.id} tooltip={tooltip}>
              {/* A real <label> for the InputSwitch, so pressing anywhere on
                  the row — the text included — toggles it. Padding matches
                  LineItemButton so it lines up with the rows around it.

                  It takes a tab stop only while disabled. The InputSwitch is a
                  native disabled button then, so it cannot be focused, and the
                  tooltip explaining why would be reachable by pointer alone.
                  Enabled, the InputSwitch carries the focus and the tooltip opens
                  from it, so a stop here would only be a second one. */}
              <label
                htmlFor={`${listId}-${item.id}`}
                className={
                  item.disabled
                    ? "block w-full p-1.5"
                    : "block w-full cursor-pointer p-1.5"
                }
                // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- the stop exists so a keyboard can reach the tooltip that says why the row is disabled; its InputSwitch is a disabled button and cannot hold focus
                tabIndex={item.disabled ? 0 : undefined}
              >
                <ContentAction
                  sizePreset="main-ui"
                  padding={0.5}
                  center
                  icon={
                    item.leading
                      ? ((() =>
                          item.leading) as React.FunctionComponent<IconProps>)
                      : undefined
                  }
                  rightChildren={
                    <InputSwitch
                      id={`${listId}-${item.id}`}
                      checked={item.isEnabled}
                      onCheckedChange={item.onToggle}
                      aria-label={t("switchList.toggle.ariaLabel", {
                        name: item.label,
                      })}
                      disabled={item.disabled}
                    />
                  }
                  title={item.label}
                />
              </label>
            </Tooltip>
          );
        }),
      ]}
    </PopoverMenu>
  );
}
