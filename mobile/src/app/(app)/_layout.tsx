import { View } from "react-native";
import { Stack } from "expo-router";

import { AppSidebar } from "@/components/chat/AppSidebar";
import { ChatSurface } from "@/components/chat/ChatSurface";

// ChatSurface overlays the <Stack> as one persistent surface so chat routes morph in place;
// the Stack drives URLs/back-stack (chat routes render null).
export default function AppLayout() {
  return (
    <View className="flex-1">
      <Stack screenOptions={{ headerShown: false }} />
      <ChatSurface />
      <AppSidebar />
    </View>
  );
}
