"use client";

import { useState, useCallback, useRef, type ReactNode } from "react";
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

// Dwell time before hovering a row swaps away an already-open flyout, so a
// pointer passing over sibling rows en route to the flyout doesn't collapse it.
const FLYOUT_SWAP_DELAY_MS = 150;

interface FlyoutRowProps {
  icon: IconFunctionComponent;
  label: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onHoverOpen: () => void;
  onHoverLeave: () => void;
  children: ReactNode[];
}

// Nested in the main menu so Radix treats it as a dismissable-layer branch.
function FlyoutRow({
  icon,
  label,
  open,
  onOpenChange,
  onHoverOpen,
  onHoverLeave,
  children,
}: FlyoutRowProps) {
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <Popover.Trigger asChild>
        <LineItem
          icon={icon}
          selected={open}
          onPointerEnter={onHoverOpen}
          onPointerLeave={onHoverLeave}
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
  const pendingSwapRef = useRef<number | null>(null);

  const cancelPendingSwap = useCallback(() => {
    if (pendingSwapRef.current !== null) {
      window.clearTimeout(pendingSwapRef.current);
      pendingSwapRef.current = null;
    }
  }, []);

  const close = useCallback(() => {
    cancelPendingSwap();
    setOpen(false);
    setOpenKey(null);
  }, [cancelPendingSwap]);

  // Functional update keeps sibling open/close events from racing.
  const flyoutOpenChange = useCallback((key: string, next: boolean) => {
    setOpenKey((prev) => (next ? key : prev === key ? null : prev));
  }, []);

  // Opens instantly when no flyout is open; otherwise requires a short dwell
  // (cancelled on pointer-leave) before swapping or collapsing, so incidental
  // pass-overs of sibling rows don't yank the open flyout away.
  const hoverRow = useCallback(
    (key: string | null) => {
      cancelPendingSwap();
      if (openKey === null || openKey === key) {
        if (key !== null) setOpenKey(key);
        return;
      }
      pendingSwapRef.current = window.setTimeout(() => {
        pendingSwapRef.current = null;
        setOpenKey(key);
      }, FLYOUT_SWAP_DELAY_MS);
    },
    [openKey, cancelPendingSwap]
  );

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
          onHoverOpen={() => hoverRow(item.key)}
          onHoverLeave={cancelPendingSwap}
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
        // Hovering a non-flyout row collapses any open flyout (after a dwell).
        onPointerEnter={() => hoverRow(null)}
        onPointerLeave={cancelPendingSwap}
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
