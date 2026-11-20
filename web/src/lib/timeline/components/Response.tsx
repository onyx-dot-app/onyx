"use client";

import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { Presence } from "@opal/components";
import { Section } from "@opal/layouts";
import { cn } from "@opal/utils";
import { AnswerText } from "@/lib/timeline/components/AnswerText";
import {
  RESPONSE_CURSOR_ANCHOR_ATTRIBUTE,
  STREAMING_CURSOR_LOOK,
} from "@/lib/rehypeStreamingCursor";

/** The key of the cursor item (`responseCursorItem`). */
export const RESPONSE_CURSOR_KEY = "cursor";

const InCursorScopeContext = createContext(false);

/**
 * True inside a `Response` (or the `ResponseCursorScope` of its turn). A
 * streaming cursor there is a marker for the turn's one cursor, not a cursor
 * of its own.
 */
export function useInResponse(): boolean {
  return useContext(InCursorScopeContext);
}

/** How long the cursor glides when it moves to another block. */
const CURSOR_GLIDE_MS = 250;

/**
 * One item of a response, in arrival order. A `run` is a run card, `text` is
 * answer text (or anything that lines up with it, such as the cursor), and a
 * `card` is a block such as a notice or an approval card.
 */
export interface ResponseItem {
  kind: "run" | "text" | "card";
  key: React.Key;
  node: React.ReactNode;
  /**
   * Play the entry even when the item is present on the first render. Unset,
   * only items that arrive later play it.
   */
  appear?: boolean;
}

export interface ResponseProps {
  items: ResponseItem[];
}

/**
 * Keeps the turn's one cursor on its last marker (see
 * `RESPONSE_CURSOR_ANCHOR_ATTRIBUTE`). The cursor is a single element, so it
 * never restarts its pulse. Text pushes it along at once; a move between a
 * waiting slot and text, or back after it was hidden, glides. It follows its
 * marker each frame while one exists, and fades out, in place, when none
 * does.
 */
function useTurnCursor(
  rootRef: React.RefObject<HTMLDivElement | null>,
  cursorRef: React.RefObject<HTMLSpanElement | null>
): void {
  useEffect(() => {
    const root = rootRef.current;
    const cursor = cursorRef.current;
    if (!root || !cursor) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    let frame: number | null = null;
    let placed = false;
    let visible = false;
    let anchorKind: string | null = null;
    let glideUntil = 0;
    const place = () => {
      frame = null;
      const anchors = root.querySelectorAll(
        `[${RESPONSE_CURSOR_ANCHOR_ATTRIBUTE}]`
      );
      const anchor = anchors.item(anchors.length - 1);
      if (!anchor) {
        cursor.style.opacity = "0";
        visible = false;
        return;
      }
      const kind = anchor.getAttribute(RESPONSE_CURSOR_ANCHOR_ATTRIBUTE);
      if (placed && (!visible || kind !== anchorKind)) {
        glideUntil = performance.now() + CURSOR_GLIDE_MS;
      }
      anchorKind = kind;
      cursor.style.transition = reducedMotion.matches
        ? "none"
        : performance.now() < glideUntil
          ? `opacity 250ms, transform ${CURSOR_GLIDE_MS}ms ease-out`
          : "opacity 250ms";
      const rootRect = root.getBoundingClientRect();
      const anchorRect = anchor.getBoundingClientRect();
      // Physical offsets: the cursor sits at `left-0`, in any direction.
      cursor.style.transform = `translate(${anchorRect.left - rootRect.left}px, ${anchorRect.top - rootRect.top}px)`;
      cursor.style.opacity = "1";
      placed = true;
      visible = true;
      frame = requestAnimationFrame(place);
    };
    const start = () => {
      if (frame === null) place();
    };

    start();
    const observer = new MutationObserver(start);
    observer.observe(root, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, [rootRef, cursorRef]);
}

interface ResponseCursorScopeProps {
  children: React.ReactNode;
}

/**
 * Draws one cursor for everything inside it: a whole turn, which in chat can
 * span several responses. A `Response` opens its own scope unless one is
 * already open around it.
 */
export function ResponseCursorScope({ children }: ResponseCursorScopeProps) {
  const inScope = useContext(InCursorScopeContext);
  const rootRef = useRef<HTMLDivElement>(null);
  const cursorRef = useRef<HTMLSpanElement>(null);
  useTurnCursor(rootRef, cursorRef);

  if (inScope) return <>{children}</>;
  return (
    <InCursorScopeContext.Provider value>
      <div ref={rootRef} className="relative">
        {children}
        {/* The outer element places and fades the cursor; the inner one
            pulses. A pulse animates opacity, which would override the fade. */}
        <span
          ref={cursorRef}
          aria-hidden
          className="absolute top-0 left-0 pointer-events-none opacity-0"
        >
          <span className={cn(STREAMING_CURSOR_LOOK, "block")} />
        </span>
      </div>
    </InCursorScopeContext.Provider>
  );
}

/**
 * A response's layout, the same in chat and Craft: its items in arrival order,
 * 0.75rem apart, with text lined up with the run header's text.
 *
 * The spacing is the column's gap, so an item that renders nothing (a hidden
 * run) takes no space. An item that arrives after the response first renders
 * opens its space: its height grows, then it fades in, so whatever sits below
 * slides down instead of snapping. Run cards do this themselves (`RunCard`).
 * Items present on the first render, such as saved history, appear at once.
 * Text that takes the cursor item's place appears at once too: the cursor
 * moves into it.
 */
export function Response({ items }: ResponseProps) {
  const [initialKeys] = useState(() => new Set(items.map((item) => item.key)));
  // The keys of the previous render, to see text replace the cursor item.
  const [previousKeys, setPreviousKeys] = useState(() =>
    items.map((item) => item.key)
  );
  const keys = items.map((item) => item.key);
  if (
    keys.length !== previousKeys.length ||
    keys.some((key, index) => key !== previousKeys[index])
  ) {
    setPreviousKeys(keys);
  }
  const cursorReplaced =
    previousKeys.includes(RESPONSE_CURSOR_KEY) &&
    !keys.includes(RESPONSE_CURSOR_KEY);

  return (
    <ResponseCursorScope>
      <Section alignItems="stretch" gap={3} height="auto">
        {items.map((item) =>
          item.kind === "run" ? (
            <React.Fragment key={item.key}>{item.node}</React.Fragment>
          ) : (
            <Presence
              key={item.key}
              appear={
                item.appear ??
                (!initialKeys.has(item.key) &&
                  !(
                    cursorReplaced &&
                    item.kind === "text" &&
                    !previousKeys.includes(item.key)
                  ))
              }
              grow
            >
              {item.kind === "text" ? (
                <AnswerText>{item.node}</AnswerText>
              ) : (
                item.node
              )}
            </Presence>
          )
        )}
      </Section>
    </ResponseCursorScope>
  );
}

export default Response;
