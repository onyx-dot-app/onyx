import type { ReactNode } from "react";
import { View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ChatHeader } from "@/components/chat/ChatHeader";
import { InputBar } from "@/components/chat/InputBar";

interface ChatScreenProps {
  title?: string;
  children: ReactNode;
}

// Shared chrome for the authed chat screens (mirrors auth's AuthScreenShell):
// safe-area frame + header + bottom input. Screens compose this instead of
// repeating the scaffold. PR 3 makes the input interactive.
export function ChatScreen({ title, children }: ChatScreenProps) {
  return (
    <SafeAreaView
      edges={["top", "bottom"]}
      className="flex-1 bg-background-neutral-00"
    >
      <ChatHeader title={title} />
      <View className="flex-1">{children}</View>
      <InputBar disabled />
    </SafeAreaView>
  );
}

// Centered empty/landing content with the standard screen gutter — the single
// home for that gutter value, so screens never hardcode it.
export function CenteredContent({ children }: { children: ReactNode }) {
  return (
    <View className="flex-1 items-center justify-center px-24">{children}</View>
  );
}
