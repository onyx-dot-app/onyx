import { KeyboardAvoidingView, Platform, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Button, Spinner, Text } from "@/components/opal";
import { ChatHeader } from "@/components/chat/ChatHeader";
import { ChatInputBar } from "@/components/chat/ChatInputBar";
import { MessageThread } from "@/components/chat/MessageThread";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useHydrateCurrentSession } from "@/chat/useHydrateCurrentSession";

// The single chat screen. It renders whatever session is current — a brand-new
// draft (currentSessionId null) OR a session opened from Recents. Opening a recent
// just sets currentSessionId; this screen loads + hydrates that session's history
// on demand (useHydrateCurrentSession) instead of pushing a separate [sessionId]
// route. A fresh chat is started lazily via the sidebar "New Chat" (draft → real
// session on first send; see useChatSessionLifecycle).
export default function ChatScreen() {
  const insets = useSafeAreaInsets();
  const currentSessionId = useChatSessionStore((s) => s.currentSessionId);
  const { isLoading, isError, retry } = useHydrateCurrentSession();

  return (
    <View className="flex-1 bg-background-neutral-00">
      <ChatHeader />

      {isError ? (
        <View className="flex-1 items-center justify-center gap-3 px-6">
          <Text font="secondary-body" color="text-03">
            Couldn’t load this chat.
          </Text>
          <Button
            variant="default"
            prominence="secondary"
            size="sm"
            onPress={retry}
            accessibilityLabel="Try again"
          >
            Try again
          </Button>
        </View>
      ) : isLoading ? (
        <View className="flex-1 items-center justify-center">
          <Spinner size={24} color="text-03" />
        </View>
      ) : (
        <MessageThread />
      )}

      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View
          className="px-3"
          style={{ paddingBottom: Math.max(insets.bottom, 8) }}
        >
          <ChatInputBar
            sessionId={currentSessionId}
            disabled={isLoading || isError}
          />
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}
