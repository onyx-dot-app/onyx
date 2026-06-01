import type { ReactNode } from "react";
import { KeyboardAvoidingView, Platform, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Button, Spinner, Text } from "@/components/opal";
import { ChatInputBar } from "@/components/chat/ChatInputBar";
import { MessageThread } from "@/components/chat/MessageThread";

// Shared chat body for the chat + project screens. The composer renders
// unconditionally so it (and useSendMessage) stays mounted across the
// landing↔thread flip — no stream abort.
interface ChatThreadBodyProps {
  isError: boolean;
  isLoading: boolean;
  retry: () => void;
  sessionId: string | null;
  disabled: boolean;
  composerPaddingTop?: number;
  // Alternate body rendered instead of the error/loading/thread switch.
  body?: ReactNode;
}

export function ChatThreadBody({
  isError,
  isLoading,
  retry,
  sessionId,
  disabled,
  composerPaddingTop,
  body,
}: ChatThreadBodyProps) {
  const insets = useSafeAreaInsets();

  return (
    <>
      {body !== undefined ? (
        body
      ) : isError ? (
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
          style={{
            paddingBottom: Math.max(insets.bottom, 8),
            paddingTop: composerPaddingTop,
          }}
        >
          <ChatInputBar sessionId={sessionId} disabled={disabled} />
        </View>
      </KeyboardAvoidingView>
    </>
  );
}
