import "react-native-gesture-handler"; // must be first import
import "../global.css";

import { useEffect } from "react";
import { Stack } from "expo-router";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { StatusBar } from "expo-status-bar";
import * as SplashScreen from "expo-splash-screen";

import { persister, persistMaxAge, queryClient } from "@/query/client";

// Show the native Onyx splash until the first frame is ready, then reveal the app.
SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  useEffect(() => {
    // No async init yet, so hide on the first render.
    // TODO(Subash-Mohan): once useFonts + @onyx-ai/shared init land, gate this
    // behind a readiness flag (return null until ready) so text never flashes in
    // the system font before custom fonts load.
    void SplashScreen.hideAsync();
  }, []);

  return (
    <GestureHandlerRootView className="flex-1">
      <SafeAreaProvider>
        <PersistQueryClientProvider
          client={queryClient}
          persistOptions={{ persister, maxAge: persistMaxAge }}
        >
          <StatusBar style="auto" />
          <Stack screenOptions={{ headerShown: false }} />
        </PersistQueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
