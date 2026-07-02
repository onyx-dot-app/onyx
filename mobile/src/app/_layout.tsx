import "react-native-gesture-handler"; // must be first import
import "../global.css";

import { useEffect } from "react";
import { useColorScheme } from "react-native";
import { Stack } from "expo-router";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";
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
import { AuthGate } from "@/components/auth/AuthGate";

SplashScreen.preventAutoHideAsync();

// RN can't flip CSS vars like web, so the active palette is supplied via NativeWind vars() and swapped on system scheme.
const lightTheme = vars(varsLight);
const darkTheme = vars(varsDark);

export default function RootLayout() {
  const colorScheme = useColorScheme();
  const themeVars = colorScheme === "dark" ? darkTheme : lightTheme;

  useEffect(() => {
    const unbindOnline = bindOnlineManager();
    const unbindFocus = bindAppStateFocus();

    // Fonts are embedded at build time (no runtime useFonts gate), so nothing to await before the first frame.
    void SplashScreen.hideAsync();

    return () => {
      unbindOnline();
      unbindFocus();
    };
  }, []);

  return (
    <GestureHandlerRootView style={themeVars} className="flex-1">
      <KeyboardProvider>
        <SafeAreaProvider>
          <PersistQueryClientProvider
            client={queryClient}
            persistOptions={{
              persister,
              maxAge: persistMaxAge,
              dehydrateOptions,
            }}
          >
            {/* PortalHost is the last child of the themed root so the sidebar overlay renders above all screens while inheriting the vars() theme + insets. */}
            <SidebarProvider>
              <StatusBar style="auto" />
              <AuthGate>
                <Stack screenOptions={{ headerShown: false }} />
              </AuthGate>
              <PortalHost />
            </SidebarProvider>
          </PersistQueryClientProvider>
        </SafeAreaProvider>
      </KeyboardProvider>
    </GestureHandlerRootView>
  );
}
