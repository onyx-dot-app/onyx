import { View } from "react-native";
import { Stack } from "expo-router";

import { AppSidebar } from "@/components/chat/AppSidebar";
import { ChatSurface } from "@/components/chat/ChatSurface";
import { ComposerDraftProvider } from "@/components/chat/ComposerDraftProvider";
import { UploadReconciler } from "@/components/chat/UploadReconciler";

// ChatSurface overlays the <Stack> as one persistent surface (chat routes render null and morph
// in place). The composer draft lives in a context above it so it survives the morph.
export default function AppLayout() {
  return (
    <ComposerDraftProvider>
      <View className="flex-1">
        <Stack screenOptions={{ headerShown: false }} />
        <ChatSurface />
        <AppSidebar />
        <UploadReconciler />
      </View>
    </ComposerDraftProvider>
  );
}
