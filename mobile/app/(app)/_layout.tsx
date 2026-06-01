import { Redirect, Stack } from "expo-router";

import { useAuth } from "@/auth";
import { Drawer } from "@/components/drawer/Drawer";
import { DrawerProvider } from "@/components/drawer/DrawerProvider";
import { Sidebar } from "@/components/sidebar/Sidebar";

// Authenticated group: a slide-over drawer hosts navigation instead of a tab bar.
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
