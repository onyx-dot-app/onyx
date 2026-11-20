"use client";

import {
  type ReactNode,
  type TransitionEvent,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { cn } from "@opal/utils";
import { useEscapeInterrupt } from "@/hooks/useEscapeInterrupt";

// Without a reserve, the open panel is 25rem wide where its host places it.
// With one, the panel sits over the end of the nearest positioned ancestor,
// such as the app's workspace row, and a change of width never moves it.
type ChatSidePanelPlacement =
  | { reserve?: undefined; covers?: undefined; className?: string }
  | {
      // Pixels the page beside the panel gives up to it while it is open:
      // also the panel's width beside the page
      reserve: number;
      // The panel fills the row, over the page
      covers: boolean;
      className?: undefined;
    };

type ChatSidePanelProps = ChatSidePanelPlacement & {
  open: boolean;
  // Escape in the panel: closes it, or steps back inside it
  onEscape: () => void;
  // Moves focus into the panel when it opens; a host that places focus
  // itself turns this off
  focusOnOpen?: boolean;
  // What the panel shows, such as its active tab. An element outside the
  // panel that switches it becomes the element that closing focuses.
  shows?: string;
  children: ReactNode;
};

// Closed, beside the page, or over it
type PanelShape = "closed" | "beside" | "covers";

/**
 * A chat side panel (Sources, Files) that slides open. A closed panel is
 * inert and hidden once it has slid shut: not focusable and not announced.
 * Escape in it calls `onEscape`, and closing returns focus to the element
 * that had it when the panel opened, or that last switched what it shows.
 * The width slides only on a change of shape (open, close, beside or over
 * the page); a change of width within a shape, such as the row's or a drag
 * of the edge, applies at once.
 */
export function ChatSidePanel({
  open,
  onEscape,
  reserve,
  covers,
  focusOnOpen = true,
  shows,
  className,
  children,
}: ChatSidePanelProps) {
  const shape: PanelShape = !open ? "closed" : covers ? "covers" : "beside";
  const [slidShape, setSlidShape] = useState(shape);
  const [sliding, setSliding] = useState(false);
  if (slidShape !== shape) {
    setSlidShape(shape);
    setSliding(true);
  }
  const endSlide = (event: TransitionEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget && event.propertyName === "width")
      setSliding(false);
  };

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
      onTransitionEnd={endSlide}
      className={cn(
        "overflow-hidden ease-in-out duration-300 h-full outline-none",
        reserve !== undefined && "absolute inset-y-0 end-0 z-20",
        open
          ? cn(
              "visible",
              sliding && "transition-[width]",
              reserve === undefined && "w-100"
            )
          : cn("w-0 invisible", sliding && "transition-[width,visibility]"),
        className
      )}
      style={
        open && reserve !== undefined
          ? { width: covers ? "100%" : reserve }
          : undefined
      }
    >
      {children}
    </div>
  );
  if (reserve === undefined) return panel;
  return (
    <div
      className={cn(
        "h-full ease-in-out duration-300",
        sliding && "transition-[width]"
      )}
      style={{ width: open ? reserve : 0 }}
    >
      {panel}
    </div>
  );
}
