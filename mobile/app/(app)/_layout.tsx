import { Redirect, Stack } from "expo-router";

import { useAuth } from "@/auth";
import { Drawer } from "@/components/drawer/Drawer";
import { DrawerProvider } from "@/components/drawer/DrawerProvider";
import { Sidebar } from "@/components/sidebar/Sidebar";

// Authenticated flow group. ChatGPT-style: a custom slide-over drawer (Reanimated +
// gesture-handler) hosts navigation INSTEAD of a bottom tab bar. The drawer wraps the
// route navigator so the sidebar floats above content and persists across screens.
//
// Reactive auth guard (mirrors the (auth) group): bounce to login when signed out.
export default function AppLayout() {
  const { status } = useAuth();

  if (status === "loading") return null;
  if (status === "signedOut") {
    return <Redirect href={"/(auth)/login" as never} />;
  }

  return (
    <DrawerProvider>
      <Drawer sidebar={<Sidebar />}>
        <Stack screenOptions={{ headerShown: false }} />
      </Drawer>
    </DrawerProvider>
  );
}
