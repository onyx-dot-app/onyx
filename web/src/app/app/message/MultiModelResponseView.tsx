"use client";

import {
  useState,
  useCallback,
  useMemo,
  useEffect,
  useLayoutEffect,
  useRef,
} from "react";
import { FullChatState } from "@/app/app/message/messageComponents/interfaces";
import { Message } from "@/app/app/interfaces";
import { LlmManager } from "@/lib/hooks";
import { RegenerationFactory } from "@/app/app/message/messageComponents/AgentMessage";
import MultiModelPanel from "@/app/app/message/MultiModelPanel";
import { MultiModelResponse } from "@/app/app/message/interfaces";
import { setPreferredResponse } from "@/app/app/services/lib";
import {
  applyPreferredResponse,
  setMostVisibleResponseId,
} from "@/app/app/message/multiModel";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import useScreenSize from "@/hooks/useScreenSize";
import { cn } from "@opal/utils";

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
  // Blocks picking while a send is in flight, so an explicit pick can't race
  // the send's preference write and strand it off the backend mainline.
  selectionDisabled?: boolean;
  /**
   * Read-only mode for the shared view: every response stays equal-width and
   * fully visible (no selection carousel), select/hide interactions are
   * disabled, and nothing persists. The preferred response is still marked.
   */
  readOnly?: boolean;
}

// How many pixels of a non-preferred panel are visible at the viewport edge
const PEEK_W = 64;
// Uniform panel width used in the selection-mode carousel
const SELECTION_PANEL_W = 400;
// Compact width for hidden panels in the carousel track
const HIDDEN_PANEL_W = 220;
// Generation-mode panel widths (from Figma)
const GEN_PANEL_W_2 = 720; // 2 panels side-by-side
const GEN_PANEL_W_3 = 436; // 3 panels side-by-side
// Gap between panels — matches CSS gap-6 (24px)
const PANEL_GAP = 24;
// Minimum panel width. Below it the interactive layout drops to the carousel, the shared view scrolls
const MIN_PANEL_W = 300;
// Gap between full-width cards in the narrow carousel (from Figma)
const NARROW_CAROUSEL_GAP = 4;

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
  selectionDisabled = false,
  readOnly = false,
}: MultiModelResponseViewProps) {
  // preferredIndex mirrors the tree's preferred_response_id, which the backend
  // pairs with latest_child: it marks the response the flow continued through.
  // A turn never picked from (e.g. a final multi-model turn) stays unhighlighted.
  const preferredIndexFromTree = useMemo(() => {
    if (parentMessage?.preferredResponseId == null) return null;
    const match = responses.find(
      (r) => r.messageId === parentMessage.preferredResponseId
    );
    return match?.modelIndex ?? null;
  }, [parentMessage?.preferredResponseId, responses]);
  const [preferredIndex, setPreferredIndex] = useState<number | null>(
    preferredIndexFromTree
  );
  // Re-sync when the preference lands after mount (session hydration, or the
  // implicit pick made at send time), scrolling an off-screen pick into view.
  // Deselect's animation owns clearing, so only non-null values sync in.
  useEffect(() => {
    if (preferredIndexFromTree == null) return;
    setPreferredIndex(preferredIndexFromTree);
    if (!mountedRef.current) return;
    const el = panelElsRef.current.get(preferredIndexFromTree);
    // Scroll only the chat container. scrollIntoView would also scroll the
    // carousel's overflow-hidden track, permanently offsetting its transform
    // centering (see BuildMessageList and CommandMenu for the same choice).
    const scroller = el?.closest("[data-chat-scroll]") as HTMLElement | null;
    if (!el || !scroller) return;
    const elRect = el.getBoundingClientRect();
    const scRect = scroller.getBoundingClientRect();
    if (elRect.bottom < scRect.top || elRect.top > scRect.bottom) {
      scroller.scrollTo({
        top: scroller.scrollTop + elRect.top - scRect.top - 16,
        behavior: "smooth",
      });
    }
  }, [preferredIndexFromTree]);
  // Declared after the sync effect so its mount run still sees false and
  // skips the scroll for a preference that was already set at mount.
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
  }, []);
  const parentNodeId = parentMessage?.nodeId;
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
  // Measures the root container so the layout can drop to the one-at-a-time
  // carousel when the panels can't all fit side by side.
  const [containerW, setContainerW] = useState(0);
  const [rootEl, setRootEl] = useState<HTMLDivElement | null>(null);

  // Measures the overflow-hidden carousel container for responsive preferred-panel sizing.
  const [trackContainerW, setTrackContainerW] = useState(0);
  const trackContainerElRef = useRef<HTMLDivElement | null>(null);
  const [trackContainerEl, setTrackContainerEl] =
    useState<HTMLDivElement | null>(null);
  // Also feeds the container-width measurement: every layout branch must keep
  // containerW live, or a resize can never switch back to the carousel.
  const trackContainerRef = useCallback((el: HTMLDivElement | null) => {
    trackContainerElRef.current = el;
    setTrackContainerEl(el);
    setRootEl(el);
  }, []);

  // Measures the preferred panel's height to cap non-preferred panels in selection mode.
  const [preferredPanelHeight, setPreferredPanelHeight] = useState<
    number | null
  >(null);
  const [preferredPanelEl, setPreferredPanelEl] =
    useState<HTMLDivElement | null>(null);
  // Refs to each panel wrapper: deselect height animation, overflow capping,
  // and the late-pick scroll all read this map.
  const panelElsRef = useRef<Map<number, HTMLDivElement>>(new Map());
  const setPanelEl = useCallback(
    (modelIndex: number, el: HTMLDivElement | null) => {
      if (el) {
        panelElsRef.current.set(modelIndex, el);
      } else {
        panelElsRef.current.delete(modelIndex);
      }
    },
    []
  );

  useLayoutEffect(() => {
    if (!rootEl) return;
    const ro = new ResizeObserver(([entry]) => {
      setContainerW(entry?.contentRect.width ?? 0);
    });
    ro.observe(rootEl);
    setContainerW(rootEl.offsetWidth);
    return () => ro.disconnect();
  }, [rootEl]);

  // Tracks which non-preferred panels overflow the preferred height cap.
  // Measured via useLayoutEffect after maxHeight is applied to the DOM —
  // ref callbacks fire before layout and can't reliably detect overflow.
  const [overflowingPanels, setOverflowingPanels] = useState<Set<number>>(
    new Set()
  );

  useLayoutEffect(() => {
    if (preferredPanelHeight == null || preferredIndex === null) return;
    const next = new Set<number>();
    panelElsRef.current.forEach((el, idx) => {
      if (idx === preferredIndex || hiddenPanels.has(idx)) return;
      if (el.scrollHeight > el.clientHeight) next.add(idx);
    });
    setOverflowingPanels((prev) => {
      if (prev.size === next.size && Array.from(prev).every((v) => next.has(v)))
        return prev;
      return next;
    });
  }, [preferredPanelHeight, preferredIndex, hiddenPanels, responses]);

  useLayoutEffect(() => {
    if (!trackContainerEl) return;
    const ro = new ResizeObserver(([entry]) => {
      setTrackContainerW(entry?.contentRect.width ?? 0);
    });
    ro.observe(trackContainerEl);
    setTrackContainerW(trackContainerEl.offsetWidth);
    return () => ro.disconnect();
  }, [trackContainerEl]);

  useLayoutEffect(() => {
    if (!preferredPanelEl) {
      setPreferredPanelHeight(null);
      return;
    }
    const ro = new ResizeObserver(([entry]) => {
      setPreferredPanelHeight(entry?.contentRect.height ?? 0);
    });
    ro.observe(preferredPanelEl);
    setPreferredPanelHeight(preferredPanelEl.offsetHeight);
    return () => ro.disconnect();
  }, [preferredPanelEl]);

  useEffect(() => {
    return () => {
      if (deselectTimeoutRef.current !== null) {
        clearTimeout(deselectTimeoutRef.current);
        deselectTimeoutRef.current = null;
      }
    };
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

  // Carousel below the small-screen breakpoint (one step above the sidebar
  // collapse) and whenever the column cannot fit every panel side by side.
  // Outranks selection mode, a preference change never swaps it out.
  const { isSmallScreen } = useScreenSize();
  const requiredSideBySideW =
    visibleResponses.length * MIN_PANEL_W +
    (visibleResponses.length - 1) * PANEL_GAP;
  const showNarrowCarousel =
    !readOnly &&
    visibleResponses.length > 1 &&
    containerW > 0 &&
    (isSmallScreen || containerW < requiredSideBySideW);

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
      if (isGenerating || selectionDisabled) return;

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
      if (!alreadyInSelection && !showNarrowCarousel) {
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

      if (parentMessage?.messageId && response.messageId && currentSessionId) {
        setPreferredResponse(parentMessage.messageId, response.messageId).catch(
          (err) => console.error("Failed to persist preferred response:", err)
        );

        const tree = useChatSessionStore
          .getState()
          .sessions.get(currentSessionId)?.messageTree;
        const updated =
          tree && applyPreferredResponse(tree, parentMessage.nodeId, response);
        if (updated) {
          updateSessionMessageTree(currentSessionId, updated);
        }
      }
    },
    [
      isGenerating,
      selectionDisabled,
      responses,
      preferredIndex,
      showNarrowCarousel,
      parentMessage,
      currentSessionId,
      updateSessionMessageTree,
    ]
  );

  // NOTE: Deselect only clears the local tree — no backend call to clear
  // preferred_response_id. The SetPreferredResponseRequest model doesn't
  // accept null. A backend endpoint for clearing preference would be needed
  // if deselect should persist across reloads.
  const clearPreferredInTree = useCallback(() => {
    if (!parentMessage || !currentSessionId) return;
    const tree = useChatSessionStore
      .getState()
      .sessions.get(currentSessionId)?.messageTree;
    const updated =
      tree && applyPreferredResponse(tree, parentMessage.nodeId, null);
    if (updated) {
      updateSessionMessageTree(currentSessionId, updated);
    }
  }, [parentMessage, currentSessionId, updateSessionMessageTree]);

  const handleDeselectPreferred = useCallback(() => {
    // The carousel keeps every card in place, so the chip just toggles off.
    // None of the selection layout's exit choreography applies.
    if (showNarrowCarousel) {
      setPreferredIndex(null);
      clearPreferredInTree();
      return;
    }

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

      clearPreferredInTree();
    }, 450);
  }, [showNarrowCarousel, clearPreferredInTree, preferredIndex, hiddenPanels]);

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
    !readOnly &&
    preferredIndex !== null &&
    preferredIdx !== -1 &&
    !isGenerating &&
    visibleResponses.length > 1;

  useEffect(() => {
    if (isActivelySelected) setHasEnteredSelection(true);
  }, [isActivelySelected]);

  // Use the selection layout once a preferred response has been chosen, even
  // after deselect. Only fall through to generation layout before the first
  // selection or during active streaming. The read-only (shared) view stays in
  // generation layout so every response is shown equal-width. The narrow
  // carousel outranks it: at carousel widths a preference only moves the chip.
  const showSelectionMode =
    !readOnly &&
    !showNarrowCarousel &&
    (isActivelySelected || hasEnteredSelection);

  // Crossing between layouts swaps instantly, a short fade covers the swap.
  // In-layout animations (select, switch, deselect) are untouched.
  const layoutKind = showSelectionMode
    ? "selection"
    : showNarrowCarousel
      ? "carousel"
      : "row";
  const layoutKindRef = useRef(layoutKind);
  useEffect(() => {
    if (layoutKindRef.current === layoutKind) return;
    layoutKindRef.current = layoutKind;
    if (readOnly || !rootEl) return;
    const anim = rootEl.animate([{ opacity: 0.5 }, { opacity: 1 }], {
      duration: 150,
      easing: "ease-out",
    });
    return () => anim.cancel();
  }, [layoutKind, rootEl, readOnly]);

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

  // Carousel starts on the preferred card when a preference exists, else the
  // first model (the right-most side-by-side panel).
  const lastCarouselPos = Math.max(0, visibleResponses.length - 1);
  const preferredCarouselPos = visibleResponses.findIndex(
    (r) => r.modelIndex === preferredIndex
  );
  const [carouselPos, setCarouselPos] = useState(
    preferredCarouselPos !== -1 ? preferredCarouselPos : lastCarouselPos
  );
  // The track transform animates only for arrow navigation. Entry snaps and
  // resizes reposition instantly so crossing the break never plays a slide.
  const [carouselSliding, setCarouselSliding] = useState(false);
  const navToCarouselPos = useCallback((pos: number) => {
    setCarouselSliding(true);
    setCarouselPos(pos);
  }, []);
  // Breaking into the carousel keeps continuity with the wide layout: land on
  // the preferred card when one exists, else keep the last carousel position.
  const wasNarrowRef = useRef(showNarrowCarousel);
  useEffect(() => {
    const entered = showNarrowCarousel && !wasNarrowRef.current;
    wasNarrowRef.current = showNarrowCarousel;
    if (entered && preferredCarouselPos !== -1) {
      setCarouselPos(preferredCarouselPos);
    }
  }, [showNarrowCarousel, preferredCarouselPos]);
  const clampedCarouselPos = Math.min(carouselPos, lastCarouselPos);
  const currentCarouselResponse = visibleResponses[clampedCarouselPos];

  // Feed the send path's response-in-view rule from the carousel position.
  const currentCarouselMessageId = currentCarouselResponse?.messageId ?? null;
  useEffect(() => {
    if (readOnly || parentNodeId == null || !showNarrowCarousel) return;
    if (currentCarouselMessageId != null) {
      setMostVisibleResponseId(parentNodeId, currentCarouselMessageId);
    }
    return () => setMostVisibleResponseId(parentNodeId, null);
  }, [readOnly, parentNodeId, showNarrowCarousel, currentCarouselMessageId]);

  // Build panel props — isHidden reflects actual hidden state
  const buildPanelProps = useCallback(
    (response: MultiModelResponse, isNonPreferred: boolean) => ({
      provider: response.provider,
      modelName: response.modelName,
      displayName: response.displayName,
      isPreferred: preferredIndex === response.modelIndex,
      isHidden: hiddenPanels.has(response.modelIndex),
      isNonPreferredInSelection: isNonPreferred,
      readOnly,
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
      isGenerating,
      selectionDisabled,
    }),
    [
      preferredIndex,
      hiddenPanels,
      readOnly,
      selectionDisabled,
      handleSelectPreferred,
      handleDeselectPreferred,
      toggleVisibility,
      chatState,
      llmManager,
      otherMessagesCanSwitchTo,
      onMessageSelection,
      onRegenerate,
      parentMessage,
      isGenerating,
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

    // Uniform width shrinks with the container so the deselected track never
    // overflows and clips headers at mid widths.
    const uniformPanelW = Math.max(
      MIN_PANEL_W,
      Math.min(
        SELECTION_PANEL_W,
        trackContainerW > 0
          ? (trackContainerW -
              hiddenPanels.size * HIDDEN_PANEL_W -
              (n - 1) * PANEL_GAP) /
              (visibleResponses.length || 1)
          : SELECTION_PANEL_W
      )
    );

    const selectionWidths = responses.map((r, i) => {
      if (hiddenPanels.has(r.modelIndex)) return HIDDEN_PANEL_W;
      if (i === preferredIdx) return dynamicPrefW;
      return uniformPanelW;
    });

    const panelLeftEdges = selectionWidths.reduce<number[]>((acc, w, i) => {
      acc.push(i === 0 ? 0 : acc[i - 1]! + selectionWidths[i - 1]! + PANEL_GAP);
      return acc;
    }, []);

    const preferredCenterInTrack =
      panelLeftEdges[preferredIdx]! + selectionWidths[preferredIdx]! / 2;

    // Start position: hidden panels at HIDDEN_PANEL_W, visible at uniformPanelW
    const uniformTrackW =
      responses.reduce(
        (sum, r) =>
          sum +
          (hiddenPanels.has(r.modelIndex) ? HIDDEN_PANEL_W : uniformPanelW),
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
            const startW = isHidden ? HIDDEN_PANEL_W : uniformPanelW;
            const capped = isNonPref && preferredPanelHeight != null;
            const overflows = capped && overflowingPanels.has(r.modelIndex);
            return (
              <div
                key={r.modelIndex}
                ref={(el) => {
                  setPanelEl(r.modelIndex, el);
                  if (isPref) setPreferredPanelEl(el);
                }}
                style={{
                  width: `${selectionEntered ? finalW : startW}px`,
                  flexShrink: 0,
                  transition:
                    selectionEntered || selectionExiting
                      ? "width 0.45s cubic-bezier(0.2, 0, 0, 1)"
                      : "none",
                  maxHeight: capped ? preferredPanelHeight : undefined,
                  overflow: "clip",
                  ...(overflows
                    ? {
                        maskImage:
                          "linear-gradient(to bottom, black calc(100% - 6rem), transparent 100%)",
                        WebkitMaskImage:
                          "linear-gradient(to bottom, black calc(100% - 6rem), transparent 100%)",
                      }
                    : {}),
                }}
              >
                {/* Content is laid out at the final width so the wrapper's
                    width animation reveals it instead of rewrapping text
                    every frame, which reads as content pouring in. */}
                <div
                  style={{ width: `${finalW}px` }}
                  className={cn(isNonPref && "opacity-50")}
                >
                  <MultiModelPanel {...buildPanelProps(r, isNonPref)} />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  if (showNarrowCarousel) {
    // ── Narrow Carousel Layout (one response in view) ──
    // Full-width cards with off-canvas neighbors, per the mobile design. The
    // current card's header carries the prev/next model nav.
    const prevResponse =
      clampedCarouselPos > 0
        ? visibleResponses[clampedCarouselPos - 1]
        : undefined;
    const nextResponse =
      clampedCarouselPos < lastCarouselPos
        ? visibleResponses[clampedCarouselPos + 1]
        : undefined;
    const prevNav = prevResponse
      ? {
          provider: prevResponse.provider,
          modelName: prevResponse.modelName,
          displayName: prevResponse.displayName,
          onClick: () => navToCarouselPos(clampedCarouselPos - 1),
        }
      : undefined;
    const nextNav = nextResponse
      ? {
          provider: nextResponse.provider,
          modelName: nextResponse.modelName,
          displayName: nextResponse.displayName,
          onClick: () => navToCarouselPos(clampedCarouselPos + 1),
        }
      : undefined;
    return (
      <div ref={setRootEl} className="w-full overflow-hidden">
        {/* raw-ok: transform-driven carousel track matching the sibling selection-layout track. Section's inline gap/width styles fight the px-precise animated geometry */}
        <div
          className="flex items-start"
          style={{
            gap: `${NARROW_CAROUSEL_GAP}px`,
            transform: `translateX(-${
              clampedCarouselPos * (containerW + NARROW_CAROUSEL_GAP)
            }px)`,
            transition: carouselSliding
              ? "transform 0.45s cubic-bezier(0.2, 0, 0, 1)"
              : "none",
          }}
          onTransitionEnd={(e) => {
            if (e.target === e.currentTarget && e.propertyName === "transform")
              setCarouselSliding(false);
          }}
        >
          {visibleResponses.map((r, i) => {
            const isCurrent = i === clampedCarouselPos;
            return (
              <div
                key={r.modelIndex}
                ref={(el) => setPanelEl(r.modelIndex, el)}
                style={{ width: `${containerW}px`, flexShrink: 0 }}
              >
                <MultiModelPanel
                  {...buildPanelProps(r, false)}
                  carouselPrev={isCurrent ? prevNav : undefined}
                  carouselNext={isCurrent ? nextNav : undefined}
                />
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
    <div ref={setRootEl} className="overflow-x-auto">
      {/* raw-ok: equal-width panel row whose children carry px min/max widths, outside Section's rem spacing steps */}
      <div className="flex gap-6 items-start justify-center w-full">
        {responses.map((r) => {
          const isHidden = hiddenPanels.has(r.modelIndex);
          return (
            <div
              key={r.modelIndex}
              ref={(el) => setPanelEl(r.modelIndex, el)}
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
