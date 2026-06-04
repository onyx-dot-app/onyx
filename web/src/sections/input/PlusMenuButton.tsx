"use client";

import { useState, useCallback, type ReactNode } from "react";
import { Button, Popover } from "@opal/components";
import { SvgChevronRight, SvgPlus } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import LineItem from "@/refresh-components/buttons/LineItem";

export interface PlusMenuFlyoutItem {
  key: string;
  label: string;
  icon?: IconFunctionComponent;
  description?: string;
  rightContent?: ReactNode;
  onSelect: () => void;
}

/** A direct-action row (`onSelect`) or a flyout row (`flyoutItems`). */
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

// Nested in the main menu so Radix treats it as a dismissable-layer branch.
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
        // Hover drives open/close; suppress Radix's own dismissal so it
        // doesn't flicker closed while the pointer is still on the panel.
        onInteractOutside={(e) => e.preventDefault()}
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

  // Functional update keeps sibling open/close events from racing.
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

      <Popover.Content
        side="bottom"
        align="start"
        width="lg"
        // Don't restore focus to the + button on close, or its tooltip flashes.
        onCloseAutoFocus={(e) => e.preventDefault()}
      >
        <Popover.Menu>{menuChildren}</Popover.Menu>
      </Popover.Content>
    </Popover>
  );
}

export default PlusMenuButton;
