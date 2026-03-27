"use client";

import { SWRConfig, type State } from "swr";
import { skipRetryOnAuthError } from "@/lib/fetcher";

const CACHE_KEY = "onyx-swr-v1";

/**
 * Backs the SWR in-memory cache with sessionStorage so cached responses
 * survive page reloads. SWR still revalidates on mount (stale-while-revalidate),
 * so the UI renders immediately with cached data and updates when fresh data arrives.
 *
 * sessionStorage is used (not localStorage) so the cache is scoped to the tab
 * session and is automatically cleared when the tab is closed.
 */
function sessionStorageProvider(): Map<string, State<unknown>> {
  if (typeof window === "undefined") {
    return new Map();
  }

  // State<unknown> matches what SWR stores; the actual generic parameter is
  // resolved by each hook at read time, so unknown is the correct lower bound.
  let map: Map<string, State<unknown>>;
  try {
    map = new Map<string, State<unknown>>(
      JSON.parse(sessionStorage.getItem(CACHE_KEY) || "[]") as [
        string,
        State<unknown>,
      ][]
    );
  } catch {
    // Corrupted or unparseable cache — start fresh
    map = new Map<string, State<unknown>>();
  }

  window.addEventListener("beforeunload", () => {
    try {
      sessionStorage.setItem(
        CACHE_KEY,
        JSON.stringify(Array.from(map.entries()))
      );
    } catch {
      // Storage quota exceeded or serialization error — ignore
    }
  });

  return map;
}

export default function SWRConfigProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <SWRConfig
      value={{
        onErrorRetry: skipRetryOnAuthError,
        provider: sessionStorageProvider,
      }}
    >
      {children}
    </SWRConfig>
  );
}
