import { Stack } from "expo-router";

import { AppSidebar } from "@/components/chat/AppSidebar";

// Sidebar mounted here (not per-screen) so its overlay spans every (app) screen.
export default function AppLayout() {
  return (
    <>
      <Stack screenOptions={{ headerShown: false }} />
      <AppSidebar />
    </>
  );
}
