"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { FullChatState } from "@/app/app/message/messageComponents/interfaces";
import { Message } from "@/app/app/interfaces";
import { LlmManager } from "@/lib/hooks";
import { RegenerationFactory } from "@/app/app/message/messageComponents/AgentMessage";
import MultiModelPanel from "@/app/app/message/MultiModelPanel";
import { MultiModelResponse } from "@/app/app/message/interfaces";
import { setPreferredResponse } from "@/app/app/services/lib";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
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
  // Initialize preferredIndex from the backend's preferred_response_id when
  // loading an existing conversation.
  const [preferredIndex, setPreferredIndex] = useState<number | null>(() => {
    if (!parentMessage?.preferredResponseId) return null;
    const match = responses.find(
      (r) => r.messageId === parentMessage.preferredResponseId
    );
    return match?.modelIndex ?? null;
  });
  const [hiddenPanels, setHiddenPanels] = useState<Set<number>>(new Set());
  // Controls animation: false = panels at start position, true = panels at peek position
  const [selectionEntered, setSelectionEntered] = useState(
    () => preferredIndex !== null
  );
  // Tracks the deselect animation timeout so it can be cancelled if the user
  // re-selects a panel during the 450ms animation window.
  const deselectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // True while the reverse animation is playing (deselect → back to equal panels)
  const [selectionExiting, setSelectionExiting] = useState(false);
  // Measures the overflow-hidden carousel container for responsive preferred-panel sizing.
  const [trackContainerW, setTrackContainerW] = useState(0);
  const roRef = useRef<ResizeObserver | null>(null);
  const trackContainerElRef = useRef<HTMLDivElement | null>(null);
  const trackContainerRef = useCallback((el: HTMLDivElement | null) => {
    trackContainerElRef.current = el;
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
  // Refs to each panel wrapper for height animation on deselect
  const panelElsRef = useRef<Map<number, HTMLDivElement>>(new Map());

  // Tracks which non-preferred panels overflow the preferred height cap
  const [overflowingPanels, setOverflowingPanels] = useState<Set<number>>(
    new Set()
  );

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

  const updateSessionMessageTree = useChatSessionStore(
    (state) => state.updateSessionMessageTree
  );
  const currentSessionId = useChatSessionStore(
    (state) => state.currentSessionId
  );

  const handleSelectPreferred = useCallback(
    (modelIndex: number) => {
      if (isGenerating) return;

      // Cancel any pending deselect animation so it doesn't overwrite this selection
      if (deselectTimeoutRef.current !== null) {
        clearTimeout(deselectTimeoutRef.current);
        deselectTimeoutRef.current = null;
        setSelectionExiting(false);
      }

      // Only freeze scroll when entering selection mode for the first time.
      // When switching preferred within selection mode, panels are already
      // capped and the track just slides — no height changes to worry about.
      const alreadyInSelection = preferredIndex !== null;
      if (!alreadyInSelection) {
        const scrollContainer = trackContainerElRef.current?.closest(
          "[data-chat-scroll]"
        ) as HTMLElement | null;
        const scrollTop = scrollContainer?.scrollTop ?? 0;
        if (scrollContainer) scrollContainer.style.overflow = "hidden";

        setTimeout(() => {
          if (scrollContainer) {
            scrollContainer.scrollTop = scrollTop;
            requestAnimationFrame(() => {
              requestAnimationFrame(() => {
                if (scrollContainer) {
                  scrollContainer.scrollTop = scrollTop;
                  scrollContainer.style.overflow = "";
                }
              });
            });
          }
        }, 450);
      }

      setPreferredIndex(modelIndex);
      const response = responses.find((r) => r.modelIndex === modelIndex);
      if (!response) return;

      // Persist preferred response to backend + update local tree so the
      // input bar unblocks (awaitingPreferredSelection clears).
      if (parentMessage?.messageId && response.messageId && currentSessionId) {
        setPreferredResponse(parentMessage.messageId, response.messageId).catch(
          (err) => console.error("Failed to persist preferred response:", err)
        );

        const tree = useChatSessionStore
          .getState()
          .sessions.get(currentSessionId)?.messageTree;
        if (tree) {
          const userMsg = tree.get(parentMessage.nodeId);
          if (userMsg) {
            const updated = new Map(tree);
            updated.set(parentMessage.nodeId, {
              ...userMsg,
              preferredResponseId: response.messageId,
            });
            updateSessionMessageTree(currentSessionId, updated);
          }
        }
      }
    },
    [
      isGenerating,
      responses,
      preferredIndex,
      parentMessage,
      currentSessionId,
      updateSessionMessageTree,
    ]
  );

  // NOTE: Deselect only clears the local tree — no backend call to clear
  // preferred_response_id. The SetPreferredResponseRequest model doesn't
  // accept null. A backend endpoint for clearing preference would be needed
  // if deselect should persist across reloads.
  const handleDeselectPreferred = useCallback(() => {
    const scrollContainer = trackContainerElRef.current?.closest(
      "[data-chat-scroll]"
    ) as HTMLElement | null;

    // Animate panels back to equal positions, then clear preferred after transition
    setSelectionExiting(true);
    setSelectionEntered(false);
    deselectTimeoutRef.current = setTimeout(() => {
      deselectTimeoutRef.current = null;
      const scrollTop = scrollContainer?.scrollTop ?? 0;
      if (scrollContainer) scrollContainer.style.overflow = "hidden";

      // Before clearing state, animate each capped panel's height from
      // its current clientHeight to its natural scrollHeight.
      const animations: Animation[] = [];
      panelElsRef.current.forEach((el, modelIndex) => {
        if (modelIndex === preferredIndex) return;
        if (hiddenPanels.has(modelIndex)) return;
        const from = el.clientHeight;
        const to = el.scrollHeight;
        if (to <= from) return;
        // Lock current height, remove maxHeight cap, then animate
        el.style.maxHeight = `${from}px`;
        el.style.overflow = "hidden";
        const anim = el.animate(
          [{ maxHeight: `${from}px` }, { maxHeight: `${to}px` }],
          {
            duration: 350,
            easing: "cubic-bezier(0.2, 0, 0, 1)",
            fill: "forwards",
          }
        );
        animations.push(anim);
        anim.onfinish = () => {
          el.style.maxHeight = "";
          el.style.overflow = "";
        };
      });

      setSelectionExiting(false);
      setPreferredIndex(null);

      // Restore scroll after animations + React settle
      const restoreScroll = () => {
        requestAnimationFrame(() => {
          if (scrollContainer) {
            scrollContainer.scrollTop = scrollTop;
            scrollContainer.style.overflow = "";
          }
        });
      };

      if (animations.length > 0) {
        Promise.all(animations.map((a) => a.finished))
          .then(restoreScroll)
          .catch(restoreScroll);
      } else {
        restoreScroll();
      }

      // Clear preferredResponseId in the local tree so input bar re-gates
      if (parentMessage && currentSessionId) {
        const tree = useChatSessionStore
          .getState()
          .sessions.get(currentSessionId)?.messageTree;
        if (tree) {
          const userMsg = tree.get(parentMessage.nodeId);
          if (userMsg) {
            const updated = new Map(tree);
            updated.set(parentMessage.nodeId, {
              ...userMsg,
              preferredResponseId: undefined,
            });
            updateSessionMessageTree(currentSessionId, updated);
          }
        }
      }
    }, 450);
  }, [
    parentMessage,
    currentSessionId,
    updateSessionMessageTree,
    preferredIndex,
    hiddenPanels,
  ]);

  // Clear preferred selection when generation starts
  // Reset selection state when generation restarts
  useEffect(() => {
    if (isGenerating) {
      setPreferredIndex(null);
      setHasEnteredSelection(false);
      setSelectionExiting(false);
    }
  }, [isGenerating]);

  // Find preferred panel position — used for both the selection guard and carousel layout
  const preferredIdx = responses.findIndex(
    (r) => r.modelIndex === preferredIndex
  );

  // Track whether selection mode was ever entered — once it has been,
  // we stay in the selection layout (even after deselect) to avoid a
  // jarring DOM swap between the two layout strategies.
  const [hasEnteredSelection, setHasEnteredSelection] = useState(
    () => preferredIndex !== null
  );

  const isActivelySelected =
    preferredIndex !== null &&
    preferredIdx !== -1 &&
    !isGenerating &&
    visibleResponses.length > 1;

  useEffect(() => {
    if (isActivelySelected) setHasEnteredSelection(true);
  }, [isActivelySelected]);

  // Use the selection layout once a preferred response has been chosen,
  // even after deselect. Only fall through to generation layout before
  // the first selection or during active streaming.
  const showSelectionMode = isActivelySelected || hasEnteredSelection;

  // Trigger the slide-out animation one frame after a preferred panel is selected.
  // Uses isActivelySelected (not showSelectionMode) so re-selecting after a
  // deselect still triggers the animation.
  useEffect(() => {
    if (!isActivelySelected) {
      // Don't reset selectionEntered here — handleDeselectPreferred manages it
      return;
    }
    const raf = requestAnimationFrame(() => setSelectionEntered(true));
    return () => cancelAnimationFrame(raf);
  }, [isActivelySelected]);

  // Build panel props — isHidden reflects actual hidden state
  const buildPanelProps = useCallback(
    (response: MultiModelResponse, isNonPreferred: boolean) => ({
      provider: response.provider,
      modelName: response.modelName,
      displayName: response.displayName,
      isPreferred: preferredIndex === response.modelIndex,
      isHidden: hiddenPanels.has(response.modelIndex),
      isNonPreferredInSelection: isNonPreferred,
      onSelect: () => handleSelectPreferred(response.modelIndex),
      onDeselect: handleDeselectPreferred,
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
      errorMessage: response.errorMessage,
      errorCode: response.errorCode,
      isRetryable: response.isRetryable,
      errorStackTrace: response.errorStackTrace,
      errorDetails: response.errorDetails,
    }),
    [
      preferredIndex,
      hiddenPanels,
      handleSelectPreferred,
      handleDeselectPreferred,
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
      ? `translateX(${trackContainerW / 2 - preferredCenterInTrack}px)`
      : `translateX(${(trackContainerW - uniformTrackW) / 2}px)`;

    return (
      <div
        ref={trackContainerRef}
        className="w-full overflow-hidden"
        style={
          isActivelySelected
            ? {
                maskImage: `linear-gradient(to right, transparent 0px, black ${PEEK_W}px, black calc(100% - ${PEEK_W}px), transparent 100%)`,
                WebkitMaskImage: `linear-gradient(to right, transparent 0px, black ${PEEK_W}px, black calc(100% - ${PEEK_W}px), transparent 100%)`,
              }
            : undefined
        }
      >
        <div
          className="flex items-start"
          style={{
            gap: `${PANEL_GAP}px`,
            transition:
              selectionEntered || selectionExiting
                ? "transform 0.45s cubic-bezier(0.2, 0, 0, 1)"
                : "none",
            transform: trackTransform,
          }}
        >
          {responses.map((r, i) => {
            const isHidden = hiddenPanels.has(r.modelIndex);
            const isPref = r.modelIndex === preferredIndex;
            const isNonPref = !isHidden && !isPref && preferredIndex !== null;
            const finalW = selectionWidths[i]!;
            const startW = isHidden ? HIDDEN_PANEL_W : SELECTION_PANEL_W;
            const capped = isNonPref && preferredPanelHeight != null;
            const overflows = capped && overflowingPanels.has(r.modelIndex);
            return (
              <div
                key={r.modelIndex}
                ref={(el) => {
                  if (el) {
                    panelElsRef.current.set(r.modelIndex, el);
                  } else {
                    panelElsRef.current.delete(r.modelIndex);
                  }
                  if (isPref) preferredPanelRef(el);
                  if (capped && el) {
                    const doesOverflow = el.scrollHeight > el.clientHeight;
                    setOverflowingPanels((prev) => {
                      const had = prev.has(r.modelIndex);
                      if (doesOverflow === had) return prev;
                      const next = new Set(prev);
                      if (doesOverflow) next.add(r.modelIndex);
                      else next.delete(r.modelIndex);
                      return next;
                    });
                  }
                }}
                style={{
                  width: `${selectionEntered ? finalW : startW}px`,
                  flexShrink: 0,
                  transition:
                    selectionEntered || selectionExiting
                      ? "width 0.45s cubic-bezier(0.2, 0, 0, 1)"
                      : "none",
                  maxHeight: capped ? preferredPanelHeight : undefined,
                  overflow: capped ? "hidden" : undefined,
                  position: capped ? "relative" : undefined,
                }}
              >
                <div className={cn(isNonPref && "opacity-50")}>
                  <MultiModelPanel {...buildPanelProps(r, isNonPref)} />
                </div>
                {overflows && (
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
      <div className="flex gap-6 items-start justify-center w-full">
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
                  : {
                      flex: "1 1 0",
                      minWidth: MIN_PANEL_W,
                      maxWidth: panelWidth,
                    }
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
