import type { ConfigContext, ExpoConfig } from "expo/config";

// Dynamic Expo config. Spreads the static `app.json` (icon/splash/adaptiveIcon
// live there) and overrides the identity/native bits that EAS env can drive.
//
// NOTE: `app.json` currently sets name/scheme to "mobile"; the overrides below
// replace those. Plugins stay exactly as `app.json` lists them (expo-router +
// expo-splash-screen) — the expo-secure-store and @sentry/react-native/expo
// config plugins get added in docs 07/08 when those deps actually land.
export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: "Onyx",
  slug: "onyx-mobile",
  scheme: "onyx", // onyx:// deep links + OAuth callback
  // New Architecture is the default on SDK 56; we still declare it explicitly
  // per design doc 04. `newArchEnabled` isn't in this SDK's ExpoConfig type
  // (Expo reads it off the config object regardless), so spread it via a cast
  // to keep the rest of the config fully type-checked.
  ...({ newArchEnabled: true } as Record<string, unknown>),
  ios: {
    ...config.ios,
    bundleIdentifier: "app.onyx.mobile",
    supportsTablet: false,
  },
  android: {
    ...config.android,
    package: "app.onyx.mobile",
  },
  extra: {
    ...config.extra,
    apiBaseUrl: process.env.ONYX_API_BASE_URL,
    isCloud: process.env.ONYX_IS_CLOUD === "true",
  },
});
