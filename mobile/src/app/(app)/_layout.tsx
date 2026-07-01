import { Stack } from "expo-router";

import { AppSidebar } from "@/components/chat/AppSidebar";

// Sidebar mounted here (not per-screen) so its overlay spans every (app) screen.
// animation "none": no slide between chats — the sidebar folds away to reveal the new one.
export default function AppLayout() {
  return (
    <>
      <Stack screenOptions={{ headerShown: false, animation: "none" }} />
      <AppSidebar />
    </>
  );
}
