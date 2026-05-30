import Constants from "expo-constants";

// On-device config reader. Reads `Constants.expoConfig?.extra` once (populated
// by app.config.ts `extra`, injected per-build by EAS env) and exports a typed
// object. Everything else imports `appConfig` from here, never expo-constants
// directly. A dev fallback for apiBaseUrl lets the app boot without EAS env.
type AppConfig = {
  apiBaseUrl: string;
  isCloud: boolean;
};

const extra = (Constants.expoConfig?.extra ?? {}) as Partial<AppConfig>;

export const appConfig: AppConfig = {
  apiBaseUrl: extra.apiBaseUrl || "http://localhost:8080",
  isCloud: extra.isCloud ?? false,
};
