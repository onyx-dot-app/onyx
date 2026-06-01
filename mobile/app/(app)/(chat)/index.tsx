import { View } from "react-native";

import { ChatHeader } from "@/components/chat/ChatHeader";
import { ChatThreadBody } from "@/components/chat/ChatThreadBody";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useResetForcedToolsOnSessionChange } from "@/state/useForcedTools";
import { useHydrateCurrentSession } from "@/chat/useHydrateCurrentSession";

// The single chat screen. It renders whatever session is current — a brand-new
// draft (currentSessionId null) OR a session opened from Recents. Opening a recent
// just sets currentSessionId; this screen loads + hydrates that session's history
// on demand (useHydrateCurrentSession) instead of pushing a separate [sessionId]
// route. A fresh chat is started lazily via the sidebar "New Chat" (draft → real
// session on first send; see useChatSessionLifecycle).
export default function ChatScreen() {
  const currentSessionId = useChatSessionStore((s) => s.currentSessionId);
  const { isLoading, isError, retry } = useHydrateCurrentSession();

  // Clear any one-shot forced tool when the session or agent changes (web parity).
  useResetForcedToolsOnSessionChange();

  return (
    <View className="flex-1 bg-background-neutral-00">
      <ChatHeader />

      <ChatThreadBody
        isError={isError}
        isLoading={isLoading}
        retry={retry}
        sessionId={currentSessionId}
        disabled={isLoading || isError}
      />
    </View>
  );
}
