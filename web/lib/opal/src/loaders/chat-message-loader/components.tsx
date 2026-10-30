"use client";

import { useId } from "react";
import {
  LineLoader,
  type LineLoaderWidth,
} from "@opal/loaders/line-loader/components";
import { cn } from "@opal/utils";

type ChatMessageLoaderOrientation = "start" | "end";

type ChatMessageLoaderBubbleWidth = "1/3" | "1/2" | "2/3";

const BUBBLE_WIDTH_CLASS = {
  "1/3": "w-1/3",
  "1/2": "w-1/2",
  "2/3": "w-2/3",
} satisfies Record<ChatMessageLoaderBubbleWidth, string>;

// The line counts a random message picks from: a user message is short, a
// reply runs longer.
const LINE_RANGE = {
  end: { min: 1, max: 3 },
  start: { min: 1, max: 5 },
} satisfies Record<ChatMessageLoaderOrientation, { min: number; max: number }>;

type NonEmpty<T> = readonly [T, ...T[]];

const LAST_LINE_WIDTHS: NonEmpty<LineLoaderWidth> = [
  "1/3",
  "1/2",
  "2/3",
  "3/4",
  "full",
];
const BUBBLE_WIDTHS: NonEmpty<ChatMessageLoaderBubbleWidth> = [
  "1/3",
  "1/2",
  "2/3",
];

/**
 * A pseudo-random generator seeded from a string. Seeded from `useId`, it
 * gives each loader its own shape, the same on the server and the client and
 * on every render.
 */
function seededRandom(seed: string): () => number {
  let state = 2166136261;
  for (let index = 0; index < seed.length; index++) {
    state = Math.imul(state ^ seed.charCodeAt(index), 16777619);
  }
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let value = Math.imul(state ^ (state >>> 15), 1 | state);
    value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(items: NonEmpty<T>, random: () => number): T {
  return items[Math.floor(random() * items.length)] ?? items[0];
}

interface ChatMessageLoaderProps {
  /**
   * Which side the message sits on, following the text direction: `"end"`
   * for the user's message (a bubble), `"start"` for the reply (plain lines).
   * @default "start"
   */
  orientation?: ChatMessageLoaderOrientation;
  /**
   * Lines of text to stand in for (at least 1). Unset, a random count: 1 to
   * 3 for `"end"`, 1 to 5 for `"start"`.
   */
  lines?: number;
  /** Width of the last line. Unset, a random width. */
  lastLineWidth?: LineLoaderWidth;
  /**
   * Width of the bubble, as a share of the column (`"end"` only). Unset, a
   * random width.
   */
  bubbleWidth?: ChatMessageLoaderBubbleWidth;
}

/**
 * A chat message that has not loaded: shimmering lines in the shape of a
 * user message or a reply. Each one picks its own shape unless told one, so a
 * stack of them reads as a conversation.
 *
 * It is decorative: it is hidden from assistive technology, so a stack of
 * them does not announce "loading" once per line. Give the stack one
 * `role="status"` with a label.
 */
function ChatMessageLoader({
  orientation = "start",
  lines,
  lastLineWidth,
  bubbleWidth,
}: ChatMessageLoaderProps) {
  const random = seededRandom(useId());
  const range = LINE_RANGE[orientation];
  const lineCount =
    lines !== undefined
      ? Math.max(1, Math.round(lines))
      : range.min + Math.floor(random() * (range.max - range.min + 1));
  const lastWidth = lastLineWidth ?? pick(LAST_LINE_WIDTHS, random);

  if (orientation === "end") {
    const width = bubbleWidth ?? pick(BUBBLE_WIDTHS, random);
    return (
      <div aria-hidden className="flex w-full justify-end">
        {/* The bubble matches a user message: its shape and its tint. */}
        <div
          className={cn(
            "opal-chat-message-loader-bubble rounded-t-16 rounded-es-16 bg-background-tint-02 px-3 py-2",
            BUBBLE_WIDTH_CLASS[width]
          )}
        >
          <LineLoader lines={lineCount} width={lastWidth} />
        </div>
      </div>
    );
  }

  return (
    <div aria-hidden className="w-full">
      <LineLoader lines={lineCount} width={lastWidth} />
    </div>
  );
}

export {
  ChatMessageLoader,
  type ChatMessageLoaderProps,
  type ChatMessageLoaderOrientation,
  type ChatMessageLoaderBubbleWidth,
};
