import { LineLoader } from "@opal/loaders/line-loader/components";
import { cn } from "@opal/utils";

type ChatMessageLoaderOrientation = "left" | "right";

interface ChatMessageLoaderProps {
  /**
   * Which side the message sits on: `"right"` for the user's message (a
   * bubble), `"left"` for the reply (plain lines). @default "left"
   */
  orientation?: ChatMessageLoaderOrientation;
}

/**
 * A chat message that has not loaded: shimmering lines in the shape of a
 * user message or a reply. Stack several to stand in for a conversation.
 */
function ChatMessageLoader({ orientation = "left" }: ChatMessageLoaderProps) {
  if (orientation === "right") {
    return (
      <div className="flex w-full justify-end">
        {/* The bubble's shape matches a user message. Its tint is a step
            lighter, so the shimmer bars (tint-02) stay visible on it. */}
        <div
          className={cn(
            "w-1/2 rounded-t-16 rounded-es-16 bg-background-tint-01 px-3 py-2"
          )}
        >
          <LineLoader lines={2} width="2/3" />
        </div>
      </div>
    );
  }

  return (
    <div className="w-full">
      <LineLoader lines={3} width="2/3" />
    </div>
  );
}

export {
  ChatMessageLoader,
  type ChatMessageLoaderProps,
  type ChatMessageLoaderOrientation,
};
