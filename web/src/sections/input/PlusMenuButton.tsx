"use client";

import { useState, useCallback, type ReactNode } from "react";
import { Button, Popover } from "@opal/components";
import { SvgChevronRight, SvgPlus } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import LineItem from "@/refresh-components/buttons/LineItem";

// A single entry inside a flyout panel.
export interface PlusMenuFlyoutItem {
  key: string;
  label: string;
  icon?: IconFunctionComponent;
  description?: string;
  /** Right-aligned content (e.g. a shortcut hint or "Connect" label). */
  rightContent?: ReactNode;
  onSelect: () => void;
}

// A top-level menu row. Either a direct action (`onSelect`) or a flyout row
// (`flyoutItems`) that opens a panel to the right.
export interface PlusMenuItem {
  key: string;
  label: string;
  icon: IconFunctionComponent;
  onSelect?: () => void;
  flyoutItems?: PlusMenuFlyoutItem[];
}

export interface PlusMenuButtonProps {
  /** Menu rows. A `null` entry renders as a divider. */
  items: Array<PlusMenuItem | null>;
  disabled?: boolean;
  tooltip?: string;
  ariaLabel?: string;
}

interface FlyoutRowProps {
  icon: IconFunctionComponent;
  label: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onHoverOpen: () => void;
  children: ReactNode[];
}

// A menu row that opens a flyout panel anchored to its right. The panel is its
// own Popover nested inside the main menu's content; Radix treats nested
// portaled content as a dismissable-layer "branch", so interacting with the
// flyout doesn't close the main menu. Opens on hover (and click), matching the
// Anthropic composer menu.
function FlyoutRow({
  icon,
  label,
  open,
  onOpenChange,
  onHoverOpen,
  children,
}: FlyoutRowProps) {
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <Popover.Trigger asChild>
        <LineItem
          icon={icon}
          selected={open}
          onPointerEnter={onHoverOpen}
          rightChildren={<SvgChevronRight className="h-4 w-4 text-text-03" />}
        >
          {label}
        </LineItem>
      </Popover.Trigger>
      <Popover.Content
        side="right"
        align="start"
        sideOffset={8}
        width="lg"
        // Hover-opening shouldn't yank focus out of the textarea.
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <Popover.Menu>{children}</Popover.Menu>
      </Popover.Content>
    </Popover>
  );
}

export function PlusMenuButton({
  items,
  disabled = false,
  tooltip = "Add",
  ariaLabel = "Open add menu",
}: PlusMenuButtonProps) {
  const [open, setOpen] = useState(false);
  const [openKey, setOpenKey] = useState<string | null>(null);

  const close = useCallback(() => {
    setOpen(false);
    setOpenKey(null);
  }, []);

  // Single flyout open at a time. Functional updates keep the open/close
  // events from sibling nested popovers from racing each other.
  const flyoutOpenChange = useCallback((key: string, next: boolean) => {
    setOpenKey((prev) => (next ? key : prev === key ? null : prev));
  }, []);

  const menuChildren: ReactNode[] = items.map((item) => {
    if (item === null) return null;

    if (item.flyoutItems) {
      return (
        <FlyoutRow
          key={item.key}
          icon={item.icon}
          label={item.label}
          open={openKey === item.key}
          onOpenChange={(next) => flyoutOpenChange(item.key, next)}
          onHoverOpen={() => setOpenKey(item.key)}
        >
          {item.flyoutItems.map((sub) => (
            <LineItem
              key={sub.key}
              icon={sub.icon}
              description={sub.description}
              rightChildren={sub.rightContent}
              onClick={() => {
                sub.onSelect();
                close();
              }}
            >
              {sub.label}
            </LineItem>
          ))}
        </FlyoutRow>
      );
    }

    return (
      <LineItem
        key={item.key}
        icon={item.icon}
        onClick={() => {
          item.onSelect?.();
          close();
        }}
        // Hovering a non-flyout row collapses any open flyout.
        onPointerEnter={() => setOpenKey(null)}
      >
        {item.label}
      </LineItem>
    );
  });

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
        else setOpen(true);
      }}
    >
      <Popover.Trigger asChild>
        <Button
          icon={SvgPlus}
          prominence="tertiary"
          disabled={disabled}
          tooltip={tooltip}
          aria-label={ariaLabel}
        />
      </Popover.Trigger>

      <Popover.Content side="top" align="start" width="lg">
        <Popover.Menu>{menuChildren}</Popover.Menu>
      </Popover.Content>
    </Popover>
  );
}

export default PlusMenuButton;
