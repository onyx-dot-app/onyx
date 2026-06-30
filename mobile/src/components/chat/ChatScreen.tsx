import type { ReactNode } from "react";
import { View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { KeyboardStickyView } from "react-native-keyboard-controller";

import { ChatHeader } from "@/components/chat/ChatHeader";

interface ChatScreenProps {
  title?: string;
  children: ReactNode;
  // input bar, omitted for read-only chrome
  input?: ReactNode;
}

// Chat chrome: top-only safe area + header + keyboard-aware input (KeyboardStickyView).
export function ChatScreen({ title, children, input }: ChatScreenProps) {
  return (
    <SafeAreaView edges={["top"]} className="flex-1 bg-background-neutral-00">
      <ChatHeader title={title} />
      <View className="flex-1">{children}</View>
      {input ? <KeyboardStickyView>{input}</KeyboardStickyView> : null}
    </SafeAreaView>
  );
}

// Centered content with the standard screen gutter (defined once here).
export function CenteredContent({ children }: { children: ReactNode }) {
  return (
    <View className="flex-1 items-center justify-center px-24">{children}</View>
  );
}
