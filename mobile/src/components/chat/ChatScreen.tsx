import type { ReactNode } from "react";
import { View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { KeyboardStickyView } from "react-native-keyboard-controller";

import { ChatHeader } from "@/components/chat/ChatHeader";

interface ChatScreenProps {
  title?: string;
  // region above the composer; caller owns its flex (flex-1 MessageList, or capped project panel)
  children: ReactNode;
  input?: ReactNode;
  below?: ReactNode;
}

export function ChatScreen({ title, children, input, below }: ChatScreenProps) {
  return (
    <SafeAreaView edges={["top"]} className="flex-1 bg-background-neutral-00">
      <ChatHeader title={title} />
      {children}
      {input ? <KeyboardStickyView>{input}</KeyboardStickyView> : null}
      {below}
    </SafeAreaView>
  );
}

export function CenteredContent({ children }: { children: ReactNode }) {
  return (
    <View className="flex-1 items-center justify-center px-24">{children}</View>
  );
}
