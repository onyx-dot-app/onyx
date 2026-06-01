import type { ReactNode } from "react";
import { KeyboardAvoidingView, Platform, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Button, Spinner, Text } from "@/components/opal";
import { ChatInputBar } from "@/components/chat/ChatInputBar";
import { MessageThread } from "@/components/chat/MessageThread";

// The chat thread body shared by the single chat screen and the project screen:
// the error → loading → MessageThread switch, plus the always-mounted composer in a
// keyboard-avoiding wrapper. Hosting screens keep their own session hydration /
// forced-tool wiring; only this JSX is shared.
//
// `body` lets a host render an alternate body in place of the error/loading/thread
// switch (the project screen passes its landing panel while it's a project draft).
// The composer renders unconditionally either way, so it (and its useSendMessage
// hook) stays mounted across the landing↔thread flip — no stream abort.
interface ChatThreadBodyProps {
  isError: boolean;
  isLoading: boolean;
  retry: () => void;
  sessionId: string | null;
  disabled: boolean;
  /** Extra top padding on the composer wrapper (project screen uses 4). */
  composerPaddingTop?: number;
  /** Alternate body to render instead of the error/loading/thread switch. */
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
