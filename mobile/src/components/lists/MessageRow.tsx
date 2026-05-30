import { memo } from "react";
import { View } from "react-native";

import { Card, Text } from "@/components/opal";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MessageRole = "user" | "assistant";

export interface MessageRowProps {
  /** Who authored the message — drives alignment and surface styling. */
  role: MessageRole;
  /** The message body (placeholder; the real streaming list is doc 06). */
  text: string;
}

// ---------------------------------------------------------------------------
// Static class strings (NativeWind discipline)
// ---------------------------------------------------------------------------
//
// CRITICAL: each of these is a fully STATIC string literal. NativeWind compiles
// classes by scanning source for static strings at build time, so a template
// literal like `` `self-${align}` `` would silently produce no style. We pick a
// whole pre-written class string by role instead of interpolating fragments.

/** Row wrapper: user messages hug the right edge, assistant the left. */
const ROW_WRAPPER_USER = "w-full px-4 py-1 items-end";
const ROW_WRAPPER_ASSISTANT = "w-full px-4 py-1 items-start";

/** Bubble surface: distinct tinted backgrounds per role, capped width. */
const BUBBLE_USER = "max-w-[85%] bg-background-neutral-03 border-border-02";
const BUBBLE_ASSISTANT = "max-w-[85%] bg-background-neutral-01 border-border-02";

// ---------------------------------------------------------------------------
// MessageRow
// ---------------------------------------------------------------------------

/**
 * Canonical example of a memoized FlashList row that follows the NativeWind +
 * virtualization discipline documented in `VirtualList`.
 *
 * Discipline demonstrated here:
 *  - Wrapped in `React.memo` so it only re-renders when `role`/`text` change.
 *  - Per-row `className` is chosen from a small set of STATIC strings by role
 *    (`ROW_WRAPPER_*` / `BUBBLE_*`) — never built via interpolation.
 *  - Token-based color/typography come through the opal `Card`/`Text`
 *    primitives, which resolve dynamic colors via `style` under the hood.
 */
function MessageRowComponent({ role, text }: MessageRowProps) {
  const isUser = role === "user";
  const wrapperClass = isUser ? ROW_WRAPPER_USER : ROW_WRAPPER_ASSISTANT;
  const bubbleClass = isUser ? BUBBLE_USER : BUBBLE_ASSISTANT;

  return (
    <View className={wrapperClass}>
      <Card className={bubbleClass}>
        <Text
          font={isUser ? "main-ui-body" : "main-content-body"}
          color="text-05"
        >
          {text}
        </Text>
      </Card>
    </View>
  );
}

/**
 * Memoized so cell recycling and theme re-renders don't needlessly re-render
 * rows whose props are unchanged. The default shallow prop comparison is
 * sufficient because both props are primitives.
 */
const MessageRow = memo(MessageRowComponent);
MessageRow.displayName = "MessageRow";

export { MessageRow };
