"use client";

import {
  type KeyboardEvent,
  type PointerEvent,
  type RefObject,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useDirection } from "@radix-ui/react-direction";
import { Button } from "@opal/components";
import { SvgFold, SvgMaximize2 } from "@opal/icons";
import { cn } from "@opal/utils";
import { hasVisibleEscapeReservedLayer } from "@/hooks/useEscapeInterrupt";
import {
  DEFAULT_PANEL_PROPORTION,
  MIN_CHAT_WIDTH,
  MIN_OUTPUT_WIDTH,
  outputPanelLayout,
  proportionForWidth,
  type OutputPanelMode,
} from "@/lib/outputPanel/layout";

interface ResizeGesture {
  pointerId: number;
  proportion: number;
  frame: number | null;
}

interface UsePanelResizeOptions {
  // The workspace that the panel shares with the chat
  workspaceRef: RefObject<HTMLElement | null>;
  workspaceWidth: number;
  // The panel's medium width now, within the limits
  mediumWidth: number;
  // Saves a new proportion, when the drag or key press ends
  onResize: (proportion: number) => void;
  // A change cancels a drag in progress (a size or layout change)
  resetKey: string;
}

/**
 * Drag and keyboard resizing of an output panel. A drag previews its width
 * each frame and saves it once, on release. Arrow keys move the edge 20px
 * (80px with Shift), Home and End go to the limits, and a double click
 * restores the default width.
 */
function usePanelResize({
  workspaceRef,
  workspaceWidth,
  mediumWidth,
  onResize,
  resetKey,
}: UsePanelResizeOptions) {
  const direction = useDirection();
  const gestureRef = useRef<ResizeGesture | null>(null);
  const [previewProportion, setPreviewProportion] = useState<number | null>(
    null
  );
  const dragging = previewProportion !== null;

  useEffect(() => {
    if (!dragging) return;
    const previous = document.body.style.userSelect;
    document.body.style.userSelect = "none";
    return () => {
      document.body.style.userSelect = previous;
    };
  }, [dragging]);

  useEffect(
    () => () => {
      const gesture = gestureRef.current;
      gestureRef.current = null;
      if (gesture?.frame != null) cancelAnimationFrame(gesture.frame);
    },
    []
  );

  useEffect(() => {
    const gesture = gestureRef.current;
    if (!gesture) return;
    gestureRef.current = null;
    if (gesture.frame !== null) cancelAnimationFrame(gesture.frame);
    setPreviewProportion(null);
  }, [resetKey]);

  function resizeAt(clientX: number) {
    const gesture = gestureRef.current;
    if (!gesture) return;
    const bounds = workspaceRef.current?.getBoundingClientRect();
    if (!bounds || !bounds.width) return;
    const width =
      direction === "rtl" ? clientX - bounds.left : bounds.right - clientX;
    gesture.proportion = proportionForWidth(width, bounds.width);
    if (gesture.frame === null) {
      gesture.frame = requestAnimationFrame(() => {
        gesture.frame = null;
        if (gestureRef.current === gesture)
          setPreviewProportion(gesture.proportion);
      });
    }
  }

  function finishDrag(event: PointerEvent<HTMLDivElement>, cancelled: boolean) {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    if (!cancelled) resizeAt(event.clientX);
    gestureRef.current = null;
    if (gesture.frame !== null) cancelAnimationFrame(gesture.frame);
    if (!cancelled) onResize(gesture.proportion);
    setPreviewProportion(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  }

  return {
    // The drag's proportion while it runs, else null
    previewProportion,
    dragging,
    handleProps: {
      onPointerDown: (event: PointerEvent<HTMLDivElement>) => {
        if (event.button !== 0 || gestureRef.current) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        const proportion = workspaceWidth ? mediumWidth / workspaceWidth : 0;
        gestureRef.current = {
          pointerId: event.pointerId,
          proportion,
          frame: null,
        };
        setPreviewProportion(proportion);
      },
      onPointerMove: (event: PointerEvent<HTMLDivElement>) => {
        if (gestureRef.current?.pointerId === event.pointerId)
          resizeAt(event.clientX);
      },
      onPointerUp: (event: PointerEvent<HTMLDivElement>) =>
        finishDrag(event, false),
      onPointerCancel: (event: PointerEvent<HTMLDivElement>) =>
        finishDrag(event, true),
      onLostPointerCapture: (event: PointerEvent<HTMLDivElement>) =>
        finishDrag(event, true),
      onDoubleClick: () => onResize(DEFAULT_PANEL_PROPORTION),
      onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => {
        if (!workspaceWidth) return;
        const step = event.shiftKey ? 80 : 20;
        let nextWidth = mediumWidth;
        if (event.key === "Home") nextWidth = MIN_OUTPUT_WIDTH;
        else if (event.key === "End")
          nextWidth = workspaceWidth - MIN_CHAT_WIDTH;
        else if (event.key === "ArrowLeft")
          nextWidth += direction === "rtl" ? -step : step;
        else if (event.key === "ArrowRight")
          nextWidth += direction === "rtl" ? step : -step;
        else return;
        event.preventDefault();
        onResize(proportionForWidth(nextWidth, workspaceWidth));
      },
    },
  };
}

interface PanelResizeHandleProps {
  label: string;
  workspaceWidth: number;
  mediumWidth: number;
  // Shown and focusable only while the panel is open at medium size
  active: boolean;
  // The handle's distance from the workspace's end edge
  insetInlineEnd: string;
  transitions: boolean;
  handleProps: ReturnType<typeof usePanelResize>["handleProps"];
}

/** The draggable edge between the chat and an output panel. */
export function PanelResizeHandle({
  label,
  workspaceWidth,
  mediumWidth,
  active,
  insetInlineEnd,
  transitions,
  handleProps,
}: PanelResizeHandleProps) {
  return (
    <div
      role="separator"
      tabIndex={active ? 0 : -1}
      inert={!active}
      aria-hidden={!active}
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemin={MIN_OUTPUT_WIDTH}
      aria-valuemax={Math.max(
        MIN_OUTPUT_WIDTH,
        workspaceWidth - MIN_CHAT_WIDTH
      )}
      aria-valuenow={Math.round(mediumWidth)}
      className={cn(
        "absolute inset-y-0 z-30 w-2 cursor-col-resize touch-none hover:bg-background-tint-02 focus-visible:bg-background-tint-02 focus-visible:outline focus-visible:outline-1 focus-visible:outline-border-03",
        transitions &&
          "transition-[inset-inline-end] duration-180 ease-out motion-reduce:transition-none",
        !active && "invisible pointer-events-none"
      )}
      style={{ insetInlineEnd }}
      {...handleProps}
    />
  );
}

interface PanelSizeButtonProps {
  full: boolean;
  expandLabel: string;
  restoreLabel: string;
  onToggle: () => void;
}

/** Expands an output panel over the chat, or restores it beside the chat. */
export function PanelSizeButton({
  full,
  expandLabel,
  restoreLabel,
  onToggle,
}: PanelSizeButtonProps) {
  return (
    <Button
      icon={full ? SvgFold : SvgMaximize2}
      prominence="tertiary"
      size="sm"
      aria-label={full ? restoreLabel : expandLabel}
      tooltip={full ? restoreLabel : expandLabel}
      onClick={onToggle}
    />
  );
}

/**
 * Escape restores a full panel to medium size, unless an IME composes or a
 * visible dialog, menu or listbox takes it. It listens in the capture phase,
 * so it runs before the page's other Escape handlers, such as stopping a run,
 * whenever they were added.
 */
function useRestoreFullPanelOnEscape(full: boolean, restore: () => void): void {
  useEffect(() => {
    if (!full) return;
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (
        event.key !== "Escape" ||
        event.defaultPrevented ||
        event.isComposing ||
        hasVisibleEscapeReservedLayer()
      )
        return;
      event.preventDefault();
      restore();
    }
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [full, restore]);
}

interface UseOutputPanelWorkspaceOptions {
  // The workspace that the panel shares with the page
  workspaceRef: RefObject<HTMLElement | null>;
  // The page beside the panel, inert while the panel covers it
  pageRef: RefObject<HTMLElement | null>;
  // Takes focus from the page when the panel covers it
  coverFocusRef: RefObject<HTMLElement | null>;
  mode: OutputPanelMode;
  // The saved share of the workspace at medium size
  proportion: number;
  // Saves a proportion from a drag or a key press
  onResize: (proportion: number) => void;
  // Restores a full panel to medium size
  onRestore: () => void;
  // Keeps measuring the workspace while the panel is closed
  measureWhileClosed?: boolean;
  // The panel's session: a change cancels a drag, whose width belongs to the
  // session it started in
  sessionId: string | null;
}

/**
 * The workspace of an output panel beside a page, shared by Craft's workspace
 * and the chat page. It measures the workspace for the panel's width, lets
 * the user resize the panel, makes the covered page inert and Escape restore
 * a full panel. A narrow workspace has no size button, so Escape does not
 * restore there.
 */
export function useOutputPanelWorkspace({
  workspaceRef,
  pageRef,
  coverFocusRef,
  mode,
  proportion,
  onResize,
  onRestore,
  measureWhileClosed = false,
  sessionId,
}: UseOutputPanelWorkspaceOptions) {
  const [workspaceWidth, setWorkspaceWidth] = useState(0);
  // Measures again on opening: a closed panel keeps its last width, and a
  // panel inside the workspace mounts before the workspace's ref is set
  const open = mode !== "closed";
  const measures = open || measureWhileClosed;
  useLayoutEffect(() => {
    const element = workspaceRef.current;
    if (!measures || !element) return;
    setWorkspaceWidth(element.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWorkspaceWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [workspaceRef, measures, open]);

  const saved = outputPanelLayout(workspaceWidth, proportion);
  const resize = usePanelResize({
    workspaceRef,
    workspaceWidth,
    mediumWidth: saved.mediumWidth,
    onResize,
    resetKey: JSON.stringify([mode, saved.narrow, sessionId]),
  });
  const shown = outputPanelLayout(
    workspaceWidth,
    resize.previewProportion ?? proportion
  );
  const covers = open && (mode === "full" || saved.narrow);

  useLayoutEffect(() => {
    const page = pageRef.current;
    if (!covers || !page) return;
    if (page.contains(document.activeElement)) coverFocusRef.current?.focus();
    page.inert = true;
    return () => {
      page.inert = false;
    };
  }, [covers, pageRef, coverFocusRef]);

  useRestoreFullPanelOnEscape(mode === "full" && !saved.narrow, onRestore);

  return {
    workspaceWidth,
    // Too narrow for the page and the panel side by side
    narrow: saved.narrow,
    // The panel covers the page: full size, or a narrow workspace
    covers,
    // The medium panel's share and width, with a drag's preview
    proportion: shown.proportion,
    mediumWidth: shown.mediumWidth,
    dragging: resize.dragging,
    handleProps: resize.handleProps,
  };
}
