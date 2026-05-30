import "react-native-gesture-handler"; // must be first import
import "../global.css";

import { useEffect } from "react";
import { Stack } from "expo-router";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { BottomSheetModalProvider } from "@gorhom/bottom-sheet";
import { PortalHost } from "@rn-primitives/portal";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import * as SplashScreen from "expo-splash-screen";

import { ThemeProvider } from "@/theme/ThemeProvider";
import { useAppFonts } from "@/theme/fonts";
import { queryClient, persister, persistMaxAge, persistBuster } from "@/query/client";
import { AuthProvider } from "@/auth";

// Keep the native splash up until the Opal fonts are loaded so text never
// flashes in the system fallback face.
SplashScreen.preventAutoHideAsync();

// Root provider tree (docs 04 + 06 + 07). Order: GestureHandlerRootView >
// SafeAreaProvider > ThemeProvider > PersistQueryClientProvider > AuthProvider >
// BottomSheetModalProvider > <Stack>, with <PortalHost/> inside ThemeProvider so
// @rn-primitives overlays inherit theme vars. The Zustand chat store hydrates
// synchronously from MMKV on import (no gate). AuthProvider (doc 07) holds the JWT
// and drives the (auth) vs (app) redirect.
//
// Still-placeholder: 08 — Sentry.wrap around the default export.
export default function RootLayout() {
  const fontsLoaded = useAppFonts();

  useEffect(() => {
    if (fontsLoaded) SplashScreen.hideAsync();
  }, [fontsLoaded]);

  // Native splash stays visible until fonts resolve.
  if (!fontsLoaded) return null;

  return (
    // TODO(08): wrap this export in Sentry.wrap once @sentry/react-native is installed
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <ThemeProvider>
          <PersistQueryClientProvider
            client={queryClient}
            persistOptions={{ persister, maxAge: persistMaxAge, buster: persistBuster }}
          >
            <AuthProvider>
              <BottomSheetModalProvider>
                <Stack screenOptions={{ headerShown: false }}>
                  <Stack.Screen name="(auth)" />
                  <Stack.Screen name="(app)" />
                  <Stack.Screen name="(modals)" options={{ presentation: "modal" }} />
                  <Stack.Screen name="+not-found" />
                </Stack>
              </BottomSheetModalProvider>
              <PortalHost />
            </AuthProvider>
          </PersistQueryClientProvider>
        </ThemeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
