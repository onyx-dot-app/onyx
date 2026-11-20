"use client";

import { type ReactNode, useLayoutEffect, useRef } from "react";
import { cn } from "@opal/utils";
import { useEscapeInterrupt } from "@/hooks/useEscapeInterrupt";

interface ChatSidePanelProps {
  open: boolean;
  // Escape in the panel: closes it, or steps back inside it
  onEscape: () => void;
  // The open width: "default" is 25rem, a number is pixels
  width?: "default" | number;
  // Pixels the page beside the panel gives up to it while it is open. With
  // a reserve, the panel sits over the end of the nearest positioned
  // ancestor, such as the app's workspace row: a width over the reserve
  // covers the page, and a change of width never moves the panel.
  reserve?: number;
  // Moves focus into the panel when it opens; a host that places focus
  // itself turns this off
  focusOnOpen?: boolean;
  // Animates width changes; off while the user drags the panel's edge
  animate?: boolean;
  // What the panel shows, such as its active tab. An element outside the
  // panel that switches it becomes the element that closing focuses.
  shows?: string;
  // Where the panel sits, when its host does not place it
  className?: string;
  children: ReactNode;
}

/**
 * A chat side panel (Sources, Files) that slides open. A closed panel is
 * inert and hidden once it has slid shut: not focusable and not announced.
 * Escape in it calls `onEscape`, and closing returns focus to the element
 * that had it when the panel opened, or that last switched what it shows.
 */
export function ChatSidePanel({
  open,
  onEscape,
  width = "default",
  reserve,
  focusOnOpen = true,
  animate = true,
  shows,
  className,
  children,
}: ChatSidePanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(open);
  const shownRef = useRef(shows);

  // A layout effect, so it records the opener before a host's layout effect
  // moves focus into the panel, as a panel that covers the page does
  useLayoutEffect(() => {
    const panel = panelRef.current;
    const wasOpen = wasOpenRef.current;
    wasOpenRef.current = open;
    const switched = shownRef.current !== shows;
    shownRef.current = shows;
    if (!panel) return;
    if (open === wasOpen) {
      const focused = document.activeElement;
      if (
        open &&
        switched &&
        focused instanceof HTMLElement &&
        focused !== document.body &&
        !panel.contains(focused)
      )
        openerRef.current = focused;
      return;
    }
    if (open) {
      const focused = document.activeElement;
      openerRef.current = focused instanceof HTMLElement ? focused : null;
      if (focusOnOpen) panel.focus({ preventScroll: true });
      return;
    }
    const opener = openerRef.current;
    openerRef.current = null;
    // Only when focus was in the panel, which an inert panel drops
    const focused = document.activeElement;
    if (
      opener?.isConnected &&
      (focused === null || focused === document.body || panel.contains(focused))
    ) {
      opener.focus({ preventScroll: true });
    }
  }, [open, focusOnOpen, shows]);

  // Esc closes only the top layer: a dialog that the panel opened first.
  useEscapeInterrupt({
    enabled: open,
    onInterrupt: onEscape,
    within: panelRef,
  });

  const panel = (
    <div
      ref={panelRef}
      tabIndex={-1}
      inert={!open}
      className={cn(
        "overflow-hidden ease-in-out h-full outline-none",
        animate && "duration-300",
        reserve !== undefined && "absolute inset-y-0 end-0 z-20",
        open
          ? cn(
              "visible",
              animate && "transition-[width]",
              width === "default" && "w-100"
            )
          : cn("w-0 invisible", animate && "transition-[width,visibility]"),
        className
      )}
      style={open && typeof width === "number" ? { width } : undefined}
    >
      {children}
    </div>
  );
  if (reserve === undefined) return panel;
  return (
    <div
      className={cn(
        "h-full ease-in-out",
        animate && "transition-[width] duration-300"
      )}
      style={{ width: open ? reserve : 0 }}
    >
      {panel}
    </div>
  );
}
