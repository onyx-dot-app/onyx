"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { FullChatState } from "@/app/app/message/messageComponents/interfaces";
import { Message } from "@/app/app/interfaces";
import { LlmManager } from "@/lib/hooks";
import { RegenerationFactory } from "@/app/app/message/messageComponents/AgentMessage";
import MultiModelPanel from "@/app/app/message/MultiModelPanel";
import { MultiModelResponse } from "@/app/app/message/interfaces";
import { cn } from "@/lib/utils";

export interface MultiModelResponseViewProps {
  responses: MultiModelResponse[];
  chatState: FullChatState;
  llmManager: LlmManager | null;
  onRegenerate?: RegenerationFactory;
  parentMessage?: Message | null;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (nodeId: number) => void;
  /** Called whenever the set of hidden panel indices changes */
  onHiddenPanelsChange?: (hidden: Set<number>) => void;
}

// How many pixels of a non-preferred panel are visible at the viewport edge
const PEEK_W = 64;
// Uniform panel width used in the selection-mode carousel
const SELECTION_PANEL_W = 400;
// Compact width for hidden panels in the carousel track
const HIDDEN_PANEL_W = 220;
// Generation-mode panel widths (from Figma)
const GEN_PANEL_W_2 = 640; // 2 panels side-by-side
const GEN_PANEL_W_3 = 436; // 3 panels side-by-side
// Gap between panels — matches CSS gap-6 (24px)
const PANEL_GAP = 24;
// Minimum panel width before horizontal scroll kicks in
const MIN_PANEL_W = 300;

/**
 * Renders N model responses side-by-side with two layout modes:
 *
 * **Generation mode** — equal-width panels in a horizontally-scrollable row.
 * Panel width is determined by the number of visible (non-hidden) panels.
 *
 * **Selection mode** — activated when the user clicks a panel to mark it as
 * preferred. All panels (including hidden ones) sit in a fixed-width carousel
 * track. A CSS `translateX` transform slides the track so the preferred panel
 * is centered in the viewport; the other panels peek in from the edges through
 * a mask gradient. Non-preferred visible panels are height-capped to the
 * preferred panel's measured height, dimmed at 50% opacity, and receive a
 * bottom fade-out overlay.
 *
 * Hidden panels render as a compact header-only strip at `HIDDEN_PANEL_W` in
 * both modes and are excluded from layout width calculations.
 */
export default function MultiModelResponseView({
  responses,
  chatState,
  llmManager,
  onRegenerate,
  parentMessage,
  otherMessagesCanSwitchTo,
  onMessageSelection,
  onHiddenPanelsChange,
}: MultiModelResponseViewProps) {
  const [preferredIndex, setPreferredIndex] = useState<number | null>(null);
  const [hiddenPanels, setHiddenPanels] = useState<Set<number>>(new Set());
  // Controls animation: false = panels at start position, true = panels at peek position
  const [selectionEntered, setSelectionEntered] = useState(false);
  // Measures the overflow-hidden carousel container for responsive preferred-panel sizing.
  const [trackContainerW, setTrackContainerW] = useState(0);
  const roRef = useRef<ResizeObserver | null>(null);
  const trackContainerRef = useCallback((el: HTMLDivElement | null) => {
    carouselContainerRef.current = el;
    if (roRef.current) {
      roRef.current.disconnect();
      roRef.current = null;
    }
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      setTrackContainerW(entry?.contentRect.width ?? 0);
    });
    ro.observe(el);
    setTrackContainerW(el.offsetWidth);
    roRef.current = ro;
  }, []);

  // Measures the preferred panel's height to cap non-preferred panels in selection mode.
  const [preferredPanelHeight, setPreferredPanelHeight] = useState<
    number | null
  >(null);
  const preferredRoRef = useRef<ResizeObserver | null>(null);

  // Drag-scroll state — all refs to avoid re-renders during pointer move
  const trackRef = useRef<HTMLDivElement | null>(null);
  const carouselContainerRef = useRef<HTMLDivElement | null>(null);
  const dragStartX = useRef<number | null>(null);
  const baseTranslateX = useRef(0);
  const dragCurrentDelta = useRef(0);
  const isDraggingRef = useRef(false);
  const justDraggedRef = useRef(false);
  // Kept in sync during render so pointer-up handlers can read without stale closure
  const preferredCenterRef = useRef(0);

  const preferredPanelRef = useCallback((el: HTMLDivElement | null) => {
    if (preferredRoRef.current) {
      preferredRoRef.current.disconnect();
      preferredRoRef.current = null;
    }
    if (!el) {
      setPreferredPanelHeight(null);
      return;
    }
    const ro = new ResizeObserver(([entry]) => {
      setPreferredPanelHeight(entry?.contentRect.height ?? 0);
    });
    ro.observe(el);
    setPreferredPanelHeight(el.offsetHeight);
    preferredRoRef.current = ro;
  }, []);

  const isGenerating = useMemo(
    () => responses.some((r) => r.isGenerating),
    [responses]
  );

  // Non-hidden responses — used for layout width decisions and selection-mode gating
  const visibleResponses = useMemo(
    () => responses.filter((r) => !hiddenPanels.has(r.modelIndex)),
    [responses, hiddenPanels]
  );

  const toggleVisibility = useCallback(
    (modelIndex: number) => {
      setHiddenPanels((prev) => {
        const next = new Set(prev);
        if (next.has(modelIndex)) {
          next.delete(modelIndex);
        } else {
          // Don't hide the last visible panel
          const visibleCount = responses.length - next.size;
          if (visibleCount <= 1) return prev;
          next.add(modelIndex);
        }
        onHiddenPanelsChange?.(next);
        return next;
      });
    },
    [responses.length, onHiddenPanelsChange]
  );

  const handleSelectPreferred = useCallback(
    (modelIndex: number, fromDrag = false) => {
      if (isGenerating) return;
      if (!fromDrag && justDraggedRef.current) return;
      setPreferredIndex(modelIndex);
      const response = responses[modelIndex];
      if (!response) return;
      if (onMessageSelection) {
        onMessageSelection(response.nodeId);
      }
    },
    [isGenerating, responses, onMessageSelection]
  );

  const handleCarouselPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const track = trackRef.current;
      if (!track) return;
      dragStartX.current = e.clientX;
      dragCurrentDelta.current = 0;
      isDraggingRef.current = false;
      // Capture the current rendered translateX in pixels so drag feels anchored
      const matrix = new DOMMatrix(getComputedStyle(track).transform);
      baseTranslateX.current = matrix.m41;
      e.currentTarget.setPointerCapture(e.pointerId);
      e.currentTarget.style.cursor = "grabbing";
    },
    []
  );

  const handleCarouselPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (dragStartX.current === null) return;
      const delta = e.clientX - dragStartX.current;
      if (Math.abs(delta) > 5) isDraggingRef.current = true;
      if (!isDraggingRef.current) return;
      dragCurrentDelta.current = delta;
      const track = trackRef.current;
      if (track) {
        track.style.transition = "none";
        track.style.transform = `translateX(${
          baseTranslateX.current + delta
        }px)`;
      }
    },
    []
  );

  const handleCarouselPointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (dragStartX.current === null) return;
      const delta = dragCurrentDelta.current;
      const wasDragging = isDraggingRef.current;
      dragStartX.current = null;
      isDraggingRef.current = false;
      dragCurrentDelta.current = 0;
      e.currentTarget.style.cursor = "";
      if (!wasDragging) return;
      // Block the click event that fires after pointer release from triggering a selection
      justDraggedRef.current = true;
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          justDraggedRef.current = false;
        })
      );
      if (preferredIndex === null) return;
      const currentPrefIdx = responses.findIndex(
        (r) => r.modelIndex === preferredIndex
      );
      let nextModelIndex = preferredIndex;
      if (delta < -80) {
        // Dragged left — advance to next visible panel
        for (let i = currentPrefIdx + 1; i < responses.length; i++) {
          if (!hiddenPanels.has(responses[i]!.modelIndex)) {
            nextModelIndex = responses[i]!.modelIndex;
            break;
          }
        }
      } else if (delta > 80) {
        // Dragged right — go to previous visible panel
        for (let i = currentPrefIdx - 1; i >= 0; i--) {
          if (!hiddenPanels.has(responses[i]!.modelIndex)) {
            nextModelIndex = responses[i]!.modelIndex;
            break;
          }
        }
      }
      const track = trackRef.current;
      if (nextModelIndex !== preferredIndex) {
        // Let React re-render with the new preferred panel and animate
        handleSelectPreferred(nextModelIndex, true);
      } else {
        // Snap back to current preferred panel
        if (track) {
          track.style.transition = "transform 0.45s cubic-bezier(0.2, 0, 0, 1)";
          const snapX = trackContainerW / 2 - preferredCenterRef.current;
          track.style.transform = `translateX(${snapX}px)`;
        }
      }
    },
    [
      responses,
      preferredIndex,
      hiddenPanels,
      handleSelectPreferred,
      trackContainerW,
    ]
  );

  // Clear preferred selection when generation starts
  useEffect(() => {
    if (isGenerating) {
      setPreferredIndex(null);
    }
  }, [isGenerating]);

  // Selection mode when preferred is set, not generating, and at least 2 visible panels
  const showSelectionMode =
    preferredIndex !== null && !isGenerating && visibleResponses.length > 1;

  // Trigger the slide-out animation one frame after entering selection mode
  useEffect(() => {
    if (!showSelectionMode) {
      setSelectionEntered(false);
      return;
    }
    const raf = requestAnimationFrame(() => setSelectionEntered(true));
    return () => cancelAnimationFrame(raf);
  }, [showSelectionMode]);

  // Build panel props — isHidden reflects actual hidden state
  const buildPanelProps = useCallback(
    (response: MultiModelResponse, isNonPreferred: boolean) => ({
      modelIndex: response.modelIndex,
      provider: response.provider,
      modelName: response.modelName,
      displayName: response.displayName,
      isPreferred: preferredIndex === response.modelIndex,
      isHidden: hiddenPanels.has(response.modelIndex),
      isNonPreferredInSelection: isNonPreferred,
      onSelect: () => handleSelectPreferred(response.modelIndex),
      onToggleVisibility: () => toggleVisibility(response.modelIndex),
      agentMessageProps: {
        rawPackets: response.packets,
        packetCount: response.packetCount,
        chatState,
        nodeId: response.nodeId,
        messageId: response.messageId,
        currentFeedback: response.currentFeedback,
        llmManager,
        otherMessagesCanSwitchTo,
        onMessageSelection,
        onRegenerate,
        parentMessage,
      },
    }),
    [
      preferredIndex,
      hiddenPanels,
      handleSelectPreferred,
      toggleVisibility,
      chatState,
      llmManager,
      otherMessagesCanSwitchTo,
      onMessageSelection,
      onRegenerate,
      parentMessage,
    ]
  );

  if (showSelectionMode) {
    // ── Selection Layout (transform-based carousel) ──
    //
    // All panels (including hidden) sit in the track at their original A/B/C positions.
    // Hidden panels use HIDDEN_PANEL_W; non-preferred use SELECTION_PANEL_W;
    // preferred uses dynamicPrefW (up to GEN_PANEL_W_2).
    const preferredIdx = responses.findIndex(
      (r) => r.modelIndex === preferredIndex
    );
    const n = responses.length;

    const dynamicPrefW =
      trackContainerW > 0
        ? Math.min(trackContainerW - 2 * (PEEK_W + PANEL_GAP), GEN_PANEL_W_2)
        : GEN_PANEL_W_2;

    const selectionWidths = responses.map((r, i) => {
      if (hiddenPanels.has(r.modelIndex)) return HIDDEN_PANEL_W;
      if (i === preferredIdx) return dynamicPrefW;
      return SELECTION_PANEL_W;
    });

    const panelLeftEdges = selectionWidths.reduce<number[]>((acc, w, i) => {
      acc.push(i === 0 ? 0 : acc[i - 1]! + selectionWidths[i - 1]! + PANEL_GAP);
      return acc;
    }, []);

    const preferredCenterInTrack =
      panelLeftEdges[preferredIdx]! + selectionWidths[preferredIdx]! / 2;
    // Keep in sync for pointer-up snap-back without stale closures
    preferredCenterRef.current = preferredCenterInTrack;

    // Start position: hidden panels at HIDDEN_PANEL_W, visible at SELECTION_PANEL_W
    const uniformTrackW =
      responses.reduce(
        (sum, r) =>
          sum +
          (hiddenPanels.has(r.modelIndex) ? HIDDEN_PANEL_W : SELECTION_PANEL_W),
        0
      ) +
      (n - 1) * PANEL_GAP;

    const trackTransform = selectionEntered
      ? `translateX(calc(50% - ${preferredCenterInTrack}px))`
      : `translateX(calc(50% - ${uniformTrackW / 2}px))`;

    return (
      <div
        ref={trackContainerRef}
        className="w-full overflow-hidden cursor-grab"
        onPointerDown={handleCarouselPointerDown}
        onPointerMove={handleCarouselPointerMove}
        onPointerUp={handleCarouselPointerUp}
        onPointerCancel={handleCarouselPointerUp}
        style={{
          maskImage: `linear-gradient(to right, transparent 0px, black ${PEEK_W}px, black calc(100% - ${PEEK_W}px), transparent 100%)`,
          WebkitMaskImage: `linear-gradient(to right, transparent 0px, black ${PEEK_W}px, black calc(100% - ${PEEK_W}px), transparent 100%)`,
        }}
      >
        <div
          ref={trackRef}
          className="flex items-start"
          style={{
            gap: `${PANEL_GAP}px`,
            transition: selectionEntered
              ? "transform 0.45s cubic-bezier(0.2, 0, 0, 1)"
              : "none",
            transform: trackTransform,
          }}
        >
          {responses.map((r, i) => {
            const isHidden = hiddenPanels.has(r.modelIndex);
            const isPref = r.modelIndex === preferredIndex;
            const isNonPref = !isHidden && !isPref;
            const finalW = selectionWidths[i]!;
            const startW = isHidden ? HIDDEN_PANEL_W : SELECTION_PANEL_W;
            const capped = isNonPref && preferredPanelHeight != null;
            return (
              <div
                key={r.modelIndex}
                ref={isPref ? preferredPanelRef : undefined}
                style={{
                  width: `${selectionEntered ? finalW : startW}px`,
                  flexShrink: 0,
                  transition: selectionEntered
                    ? "width 0.45s cubic-bezier(0.2, 0, 0, 1)"
                    : "none",
                  maxHeight: capped ? preferredPanelHeight : undefined,
                  overflow: capped ? "hidden" : undefined,
                  position: capped ? "relative" : undefined,
                }}
              >
                <div className={cn(capped && "opacity-50")}>
                  <MultiModelPanel {...buildPanelProps(r, isNonPref)} />
                </div>
                {capped && (
                  <div
                    className="absolute inset-x-0 bottom-0 h-24 pointer-events-none"
                    style={{
                      background:
                        "linear-gradient(to top, var(--background-tint-01) 0%, transparent 100%)",
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // ── Generation Layout (equal panels side-by-side) ──
  // Panel width based on number of visible (non-hidden) panels.
  const panelWidth =
    visibleResponses.length <= 2 ? GEN_PANEL_W_2 : GEN_PANEL_W_3;

  return (
    <div className="overflow-x-auto">
      <div className="flex gap-6 items-start w-fit mx-auto">
        {responses.map((r) => {
          const isHidden = hiddenPanels.has(r.modelIndex);
          return (
            <div
              key={r.modelIndex}
              style={
                isHidden
                  ? {
                      width: HIDDEN_PANEL_W,
                      minWidth: HIDDEN_PANEL_W,
                      maxWidth: HIDDEN_PANEL_W,
                      flexShrink: 0,
                      overflow: "hidden" as const,
                    }
                  : { width: panelWidth, minWidth: MIN_PANEL_W }
              }
            >
              <MultiModelPanel {...buildPanelProps(r, false)} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
