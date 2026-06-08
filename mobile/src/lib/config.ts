import Constants from "expo-constants";

// Reads `expoConfig.extra` (set by app.config.ts, injected per-build by EAS) once.
// Import `appConfig` from here, never expo-constants directly. apiBaseUrl has a
// dev fallback so the app boots without EAS env.
type AppConfig = {
  apiBaseUrl: string;
  isCloud: boolean;
};

const extra = (Constants.expoConfig?.extra ?? {}) as Partial<AppConfig>;

export const appConfig: AppConfig = {
  apiBaseUrl: extra.apiBaseUrl || "http://localhost:8080",
  isCloud: extra.isCloud ?? false,
};
