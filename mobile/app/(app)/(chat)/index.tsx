import { useEffect, useRef } from "react";
import { KeyboardAvoidingView, Platform, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ChatHeader } from "@/components/chat/ChatHeader";
import { ChatInputBar } from "@/components/chat/ChatInputBar";
import { MessageThread } from "@/components/chat/MessageThread";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useStartNewChat } from "@/chat/useStartNewChat";
import { getLatestMessageChain } from "@/state/messageTree";

// New-chat screen: header + streaming message thread + composer. On mount it ensures
// a usable session (reuse the current one if it's still empty, else create a fresh
// one) so the composer is bound to a real session id from the start.
export default function ChatList() {
  const insets = useSafeAreaInsets();
  const currentSessionId = useChatSessionStore((s) => s.currentSessionId);
  const startNewChat = useStartNewChat();
  const ensuredRef = useRef(false);

  useEffect(() => {
    if (ensuredRef.current) return;
    ensuredRef.current = true;
    const state = useChatSessionStore.getState();
    const cur = state.currentSessionId
      ? state.sessions.get(state.currentSessionId)
      : null;
    const hasMessages = cur
      ? getLatestMessageChain(cur.messageTree).some((m) => m.type !== "system")
      : false;
    if (!cur || hasMessages) {
      void startNewChat();
    }
  }, [startNewChat]);

  return (
    <View className="flex-1 bg-background-neutral-00">
      <ChatHeader />
      <MessageThread />
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View
          className="px-3"
          style={{ paddingBottom: Math.max(insets.bottom, 8) }}
        >
          <ChatInputBar sessionId={currentSessionId} />
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}
