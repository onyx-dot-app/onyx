import "react-native-gesture-handler"; // must be first import
import "../global.css";

import { useEffect } from "react";
import { useColorScheme } from "react-native";
import { Stack } from "expo-router";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { StatusBar } from "expo-status-bar";
import * as SplashScreen from "expo-splash-screen";
import { vars } from "nativewind";
import { varsLight, varsDark } from "@onyx-ai/shared/native";
import { PortalHost } from "@rn-primitives/portal";

import {
  dehydrateOptions,
  persister,
  persistMaxAge,
  queryClient,
} from "@/query/client";
import { bindAppStateFocus } from "@/query/focus";
import { bindOnlineManager } from "@/query/online";
import { SidebarProvider } from "@/components/sidebar";

// Show the native Onyx splash until the first frame is ready, then reveal the app.
SplashScreen.preventAutoHideAsync();

// Design tokens flow from @onyx-ai/shared. Web flips CSS variables via the `.dark`
// class; React Native can't, so we supply the active palette at the app root through
// NativeWind vars() and swap light/dark with the system color scheme. Semantic
// classes (e.g. `bg-background-neutral-00`) reference these variables, so they adapt
// automatically — no `dark:` modifiers at call-sites, exactly like web.
const lightTheme = vars(varsLight);
const darkTheme = vars(varsDark);

export default function RootLayout() {
  const colorScheme = useColorScheme();
  const themeVars = colorScheme === "dark" ? darkTheme : lightTheme;

  useEffect(() => {
    // Wire React Native connectivity + foreground state into TanStack Query so
    // queries pause offline and refetch on reconnect / app resume.
    const unbindOnline = bindOnlineManager();
    const unbindFocus = bindAppStateFocus();

    // No async init to await before the first frame. Custom fonts (Hanken Grotesk,
    // DM Mono, from the @expo-google-fonts/* packages) are embedded into the native
    // binary at build time via the expo-font config plugin (see app.json), so they're
    // registered before React mounts — no runtime useFonts / readiness gate is needed
    // and text never flashes in the system font. Hide the splash on the first render.
    void SplashScreen.hideAsync();

    return () => {
      unbindOnline();
      unbindFocus();
    };
  }, []);

  return (
    <GestureHandlerRootView style={themeVars} className="flex-1">
      <SafeAreaProvider>
        <PersistQueryClientProvider
          client={queryClient}
          persistOptions={{
            persister,
            maxAge: persistMaxAge,
            dehydrateOptions,
          }}
        >
          {/* SidebarProvider owns the shared open/closed (folded) state so any screen
              can open the sidebar and the portalled overlay can read it. PortalHost is
              the last child of the themed root, so the overlay renders above all screens
              while still inheriting the vars() theme + safe-area insets. */}
          <SidebarProvider>
            <StatusBar style="auto" />
            <Stack screenOptions={{ headerShown: false }} />
            <PortalHost />
          </SidebarProvider>
        </PersistQueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
