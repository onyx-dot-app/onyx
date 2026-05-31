import { memo, useCallback, useEffect, useMemo, useRef } from "react";
import {
  ScrollView,
  View,
  type NativeSyntheticEvent,
  type NativeScrollEvent,
} from "react-native";

import { Text } from "@/components/opal";
import { MessageRow } from "@/components/lists/MessageRow";
import { AgentMessage } from "@/components/message/AgentMessage";
import { CitationSheetProvider } from "@/components/message/sources/CitationSheet";
import type { FullChatState } from "@/components/message/interfaces";
import {
  useCurrentChatState,
  useCurrentMessageHistory,
  useCurrentPersonaId,
} from "@/state/chatSessionStore";
import { usePersonas } from "@/query/personas";
import type { Message, MinimalAgent } from "@/lib/types";

// Renders the current session's message chain (user bubbles + the rich
// AgentMessage timeline for assistant turns), auto-scrolling to the newest
// content while the user stays near the bottom.

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

// Assistant turn: builds a STABLE per-message chatState (so non-streaming turns
// don't re-render on every flush) and renders the AgentMessage timeline.
const AssistantTurn = memo(function AssistantTurn({
  message,
  agent,
}: {
  message: Message;
  agent: MinimalAgent;
}) {
  const chatState = useMemo<FullChatState>(
    () => ({
      agent,
      docs: message.documents ?? null,
      citations: message.citations,
    }),
    [agent, message.documents, message.citations]
  );

  return (
    <View style={{ paddingHorizontal: 4, paddingVertical: 4 }}>
      <AgentMessage
        rawPackets={message.packets}
        packetCount={message.packetCount}
        nodeId={message.nodeId}
        chatState={chatState}
        processingDurationSeconds={message.processingDurationSeconds}
      />
    </View>
  );
});

const MessageItem = memo(function MessageItem({
  message,
  agent,
}: {
  message: Message;
  agent: MinimalAgent;
}) {
  if (message.type === "user") {
    return <MessageRow role="user" text={message.message} files={message.files} />;
  }
  if (message.type === "error") {
    return <ErrorMessage text={message.message} />;
  }
  return <AssistantTurn message={message} agent={agent} />;
});

export function MessageThread() {
  const history = useCurrentMessageHistory();
  const chatState = useCurrentChatState();
  const personaId = useCurrentPersonaId();
  const personas = usePersonas();
  const scrollRef = useRef<ScrollView>(null);
  const nearBottomRef = useRef(true);

  // Resolve the agent for the timeline avatar; stable until persona data changes.
  const agent = useMemo<MinimalAgent>(() => {
    const found = personas.data?.find((p) => p.id === personaId);
    return (
      found ?? ({ id: personaId ?? 0, name: "", description: "" } as MinimalAgent)
    );
  }, [personas.data, personaId]);

  const visible = history.filter((m) => m.type !== "system");
  const streaming = chatState === "loading" || chatState === "streaming";

  // Pin to the newest content only when the user is already near the bottom
  // (so they can scroll up to read history mid-stream without being yanked).
  useEffect(() => {
    if (nearBottomRef.current) {
      scrollRef.current?.scrollToEnd({ animated: !streaming });
    }
  }, [visible.length, chatState, streaming]);

  const onScroll = useCallback(
    (e: NativeSyntheticEvent<NativeScrollEvent>) => {
      const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
      const distanceFromBottom =
        contentSize.height - (contentOffset.y + layoutMeasurement.height);
      nearBottomRef.current = distanceFromBottom < 120;
    },
    []
  );

  return (
    <CitationSheetProvider>
      <ScrollView
        ref={scrollRef}
        className="flex-1"
        contentContainerStyle={{ paddingVertical: 8 }}
        keyboardShouldPersistTaps="handled"
        onScroll={onScroll}
        scrollEventThrottle={16}
        onContentSizeChange={() => {
          if (nearBottomRef.current) {
            scrollRef.current?.scrollToEnd({ animated: false });
          }
        }}
      >
        {visible.map((m) => (
          <MessageItem key={m.nodeId} message={m} agent={agent} />
        ))}
      </ScrollView>
    </CitationSheetProvider>
  );
}
