"use client";

// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).
import {
  type RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
} from "react";
import {
  chatFindTextKey,
  collectChatFindRanges,
  createChatFindPainter,
  openDetailsAround,
  scrollRangeIntoView,
  scrollRowIntoView,
  type ChatFindPainter,
} from "@/lib/chatFind/highlights";
import type { ChatFindMatch } from "@/lib/chatFind/match";

interface ChatFindHighlightsInput {
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  releaseFollowing: () => void;
  query: string;
  match: ChatFindMatch | null;
  /** Changes with each search or step, so the same match is shown again. */
  matchKey: string | null;
}

interface RevealState {
  painter: ChatFindPainter | null;
  ranges: Map<string, Range[]>;
  revealed: string | null;
  rowRequested: string | null;
}

/**
 * Highlights the matches in the mounted rows and brings the active one into
 * view. A row that is not mounted is first scrolled near the view, which
 * mounts it; the repaint that follows shows the match itself.
 */
export function useChatFindHighlights({
  scrollContainerRef,
  releaseFollowing,
  query,
  match,
  matchKey,
}: ChatFindHighlightsInput): void {
  const latestRef = useRef({ match, matchKey, releaseFollowing });
  useLayoutEffect(() => {
    latestRef.current = { match, matchKey, releaseFollowing };
  });
  const stateRef = useRef<RevealState>({
    painter: null,
    ranges: new Map(),
    revealed: null,
    rowRequested: null,
  });

  const selectAndReveal = useCallback(() => {
    const state = stateRef.current;
    const { match, matchKey, releaseFollowing } = latestRef.current;
    const range = match
      ? (state.ranges.get(chatFindTextKey(match.kind, match.nodeId))?.[
          match.occurrence
        ] ?? null)
      : null;
    state.painter?.select(range);
    const container = scrollContainerRef.current;
    if (!container || !match || !matchKey || state.revealed === matchKey) {
      return;
    }
    if (range) {
      state.revealed = matchKey;
      openDetailsAround(range, container);
      scrollRangeIntoView(container, range, releaseFollowing);
      return;
    }
    if (state.rowRequested === matchKey) return;
    const row = document.getElementById(match.rowId);
    if (!row || !container.contains(row)) return;
    state.rowRequested = matchKey;
    scrollRowIntoView(container, row, releaseFollowing);
  }, [scrollContainerRef]);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container || !query) return;
    const state = stateRef.current;
    const painter = createChatFindPainter();
    state.painter = painter;
    const repaint = () => {
      state.ranges = collectChatFindRanges(container, query);
      painter.paint(state.ranges);
      selectAndReveal();
    };
    let frame: number | null = null;
    const observer = new MutationObserver(() => {
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        repaint();
      });
    });
    observer.observe(container, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    repaint();
    return () => {
      observer.disconnect();
      if (frame !== null) cancelAnimationFrame(frame);
      painter.clear();
      state.painter = null;
      state.ranges = new Map();
    };
  }, [scrollContainerRef, query, selectAndReveal]);

  useEffect(() => {
    selectAndReveal();
  }, [matchKey, selectAndReveal]);
}
