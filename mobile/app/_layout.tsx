import "react-native-gesture-handler"; // must be first import
import "../global.css";

import { Stack } from "expo-router";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { ThemeProvider } from "@/theme/ThemeProvider";

// Root provider tree for the Onyx mobile app shell (design doc 04).
//
// Only providers backed by installed packages are real here. The rest are
// commented placeholders owned by sibling docs and wired in when their deps
// land — do NOT import them until then:
//   - 06: QueryClientProvider (TanStack Query), StoreHydrationGate (Zustand)
//   - 07: AuthProvider (PAT/session; drives the (auth) vs (app) redirect)
//   - 08: Sentry.wrap around the default export
//
// Nesting order (outer -> inner): Sentry > GestureHandlerRootView >
// SafeAreaProvider > ThemeProvider > QueryClientProvider > AuthProvider >
// StoreHydrationGate > <Stack>.
export default function RootLayout() {
  return (
    // TODO(08): wrap this export in Sentry.wrap once @sentry/react-native is installed
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <ThemeProvider>
          {/* TODO(06): <QueryClientProvider client={queryClient}> */}
          {/* TODO(07): <AuthProvider> — drives (auth) vs (app) redirect */}
          {/* TODO(06): <StoreHydrationGate> — Zustand persist rehydrate */}
          <Stack screenOptions={{ headerShown: false }}>
            <Stack.Screen name="(auth)" />
            <Stack.Screen name="(app)" />
            <Stack.Screen name="(modals)" options={{ presentation: "modal" }} />
            <Stack.Screen name="+not-found" />
          </Stack>
          {/* TODO(06): </StoreHydrationGate> */}
          {/* TODO(07): </AuthProvider> */}
          {/* TODO(06): </QueryClientProvider> */}
        </ThemeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
