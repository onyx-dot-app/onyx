import { memo, useEffect, useRef } from "react";
import { ActivityIndicator, ScrollView, View } from "react-native";

import { Text } from "@/components/opal";
import { MessageRow } from "@/components/lists/MessageRow";
import { useToken } from "@/theme/ThemeProvider";
import {
  useCurrentChatState,
  useCurrentMessageHistory,
} from "@/state/chatSessionStore";
import type { Message } from "@/lib/types";

// Renders the current session's message chain (user bubbles + streaming assistant
// markdown), auto-scrolling to the newest content. Reads the store's live message
// tree, so it updates as packets stream in via useSendMessage.

// Left-aligned assistant message: markdown body, or a "thinking" spinner while the
// node is still empty and the stream is in flight.
const AssistantMessage = memo(function AssistantMessage({
  text,
  pending,
}: {
  text: string;
  pending: boolean;
}) {
  const spinnerColor = useToken("text-03");
  if (!text) {
    return pending ? (
      <View className="w-full flex-row items-center gap-2 px-4 py-2">
        <ActivityIndicator size="small" color={spinnerColor} />
        <Text font="secondary-body" color="text-03">
          Thinking…
        </Text>
      </View>
    ) : null;
  }
  // Plain text for now; markdown rendering needs a `punycode` polyfill for
  // markdown-it under Metro (follow-up).
  return (
    <View className="w-full px-4 py-1">
      <Text font="main-content-body" color="text-05">
        {text}
      </Text>
    </View>
  );
});

const ErrorMessage = memo(function ErrorMessage({ text }: { text: string }) {
  return (
    <View className="w-full px-4 py-1">
      <View className="rounded-[8px] border border-action-danger-05 bg-background-neutral-01 px-3 py-2">
        <Text font="secondary-body" color="action-text-danger-05">
          {text || "Something went wrong."}
        </Text>
      </View>
    </View>
  );
});

const MessageItem = memo(function MessageItem({
  message,
  isLast,
  streaming,
}: {
  message: Message;
  isLast: boolean;
  streaming: boolean;
}) {
  if (message.type === "user") {
    return (
      <MessageRow role="user" text={message.message} files={message.files} />
    );
  }
  if (message.type === "error") {
    return <ErrorMessage text={message.message} />;
  }
  // assistant (system nodes are filtered out before render)
  return <AssistantMessage text={message.message} pending={isLast && streaming} />;
});

export function MessageThread() {
  const history = useCurrentMessageHistory();
  const chatState = useCurrentChatState();
  const scrollRef = useRef<ScrollView>(null);

  const visible = history.filter((m) => m.type !== "system");
  const streaming = chatState === "loading" || chatState === "streaming";

  // Keep pinned to the newest content as it streams in.
  useEffect(() => {
    scrollRef.current?.scrollToEnd({ animated: true });
  }, [visible.length, chatState]);

  return (
    <ScrollView
      ref={scrollRef}
      className="flex-1"
      contentContainerStyle={{ paddingVertical: 8 }}
      keyboardShouldPersistTaps="handled"
      onContentSizeChange={() =>
        scrollRef.current?.scrollToEnd({ animated: true })
      }
    >
      {visible.map((m, i) => (
        <MessageItem
          key={m.nodeId}
          message={m}
          isLast={i === visible.length - 1}
          streaming={streaming}
        />
      ))}
    </ScrollView>
  );
}
