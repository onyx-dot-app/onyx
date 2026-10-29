import { LineLoader } from "@opal/loaders/line-loader/components";

type ChatMessageLoaderOrientation = "start" | "end";

interface ChatMessageLoaderProps {
  /**
   * Which side the message sits on, following the text direction: `"end"`
   * for the user's message (a bubble), `"start"` for the reply (plain lines).
   * @default "start"
   */
  orientation?: ChatMessageLoaderOrientation;
}

/**
 * A chat message that has not loaded: shimmering lines in the shape of a
 * user message or a reply. Stack several to stand in for a conversation.
 */
function ChatMessageLoader({ orientation = "start" }: ChatMessageLoaderProps) {
  if (orientation === "end") {
    return (
      <div className="flex w-full justify-end">
        {/* The bubble matches a user message: its shape and its tint. */}
        <div className="opal-chat-message-loader-bubble w-1/2 rounded-t-16 rounded-es-16 bg-background-tint-02 px-3 py-2">
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
