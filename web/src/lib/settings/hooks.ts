"use client";

/**
 * Application settings hooks.
 *
 * Provides access to the `CombinedSettings` context populated by
 * `SettingsProvider`. For embedding model / indexing configuration hooks,
 * see `lib/indexing/hooks.ts`.
 */

import { createContext, useContext } from "react";
import { CombinedSettings } from "@/interfaces/settings";

// ─── Settings Context ───────────────────────────────────────────────────────

/**
 * React context that carries the combined application + enterprise settings.
 * Populated by `SettingsProvider` at the root of the app.
 *
 * Consume via `useSettingsContext()` rather than reading this directly —
 * the hook throws a descriptive error when used outside the provider.
 */
export const SettingsContext = createContext<CombinedSettings | null>(null);

// ─── Context-based Hooks ────────────────────────────────────────────────────

/**
 * Access the combined application + enterprise settings from context.
 *
 * Throws if used outside a `SettingsProvider`. This is the primary hook
 * for the vast majority of components — it reads the already-fetched,
 * memoized `CombinedSettings` without triggering any additional network
 * requests.
 *
 * @example
 * const { settings, enterpriseSettings, appName } = useSettingsContext();
 */
export function useSettingsContext() {
  const context = useContext(SettingsContext);
  if (context === null) {
    throw new Error(
      "useSettingsContext must be used within a SettingsProvider"
    );
  }
  return context;
}

/**
 * Returns `true` when the vector database is enabled.
 *
 * Shorthand for `useSettingsContext().settings.vector_db_enabled !== false`.
 * When `DISABLE_VECTOR_DB` is set on the server, connectors, RAG search,
 * document sets, and related features are unavailable.
 */
export function useVectorDbEnabled(): boolean {
  const settings = useSettingsContext();
  return settings.settings.vector_db_enabled !== false;
}
