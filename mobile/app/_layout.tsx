import "react-native-gesture-handler"; // must be first import
import "../global.css";

import { useEffect } from "react";
import { Stack } from "expo-router";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { BottomSheetModalProvider } from "@gorhom/bottom-sheet";
import { PortalHost } from "@rn-primitives/portal";
import * as SplashScreen from "expo-splash-screen";

import { ThemeProvider } from "@/theme/ThemeProvider";
import { useAppFonts } from "@/theme/fonts";

// Keep the native splash up until the Opal fonts are loaded so text never
// flashes in the system fallback face.
SplashScreen.preventAutoHideAsync();

// Root provider tree for the Onyx mobile app shell (design doc 04).
//
// Real providers (deps installed): GestureHandlerRootView > SafeAreaProvider >
// ThemeProvider > BottomSheetModalProvider > <Stack>, with <PortalHost/> inside
// ThemeProvider so @rn-primitives overlays (Modal/Popover) inherit theme vars.
//
// Commented placeholders owned by sibling docs (wired when their deps land):
//   - 06: QueryClientProvider (TanStack Query), StoreHydrationGate (Zustand)
//   - 07: AuthProvider (PAT/session; drives the (auth) vs (app) redirect)
//   - 08: Sentry.wrap around the default export
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
          {/* TODO(06): <QueryClientProvider client={queryClient}> */}
          {/* TODO(07): <AuthProvider> — drives (auth) vs (app) redirect */}
          {/* TODO(06): <StoreHydrationGate> — Zustand persist rehydrate */}
          <BottomSheetModalProvider>
            <Stack screenOptions={{ headerShown: false }}>
              <Stack.Screen name="(auth)" />
              <Stack.Screen name="(app)" />
              <Stack.Screen name="(modals)" options={{ presentation: "modal" }} />
              <Stack.Screen name="+not-found" />
            </Stack>
          </BottomSheetModalProvider>
          {/* TODO(06): </StoreHydrationGate> </AuthProvider> </QueryClientProvider> */}
          <PortalHost />
        </ThemeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
