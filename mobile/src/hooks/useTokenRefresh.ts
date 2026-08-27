/*
 * iOS suspends JS timers while backgrounded, so foregrounding is the real trigger here; the
 * interval only covers a session that stays in the foreground.
 */
import { useEffect, useRef } from "react";
import { AppState, type AppStateStatus } from "react-native";

import { refreshToken } from "@/api/auth/sessionManager";

const REFRESH_INTERVAL_MS = 600_000;
// Ticks can bunch up after a suspend; keep interval-driven attempts a period apart.
const INTERVAL_MIN_GAP_MS = REFRESH_INTERVAL_MS - 60_000;
const FOREGROUND_MIN_GAP_MS = 60_000;

/**
 * @param enabled Pass only once identity is confirmed — refreshing before `/me` settles would
 * race the persisted-cache restore, and a rejected token wipes that cache.
 */
export function useTokenRefresh(enabled: boolean): void {
  const lastAttemptAtRef = useRef(0);

  useEffect(() => {
    if (!enabled) return;

    function attempt(minGapMs: number): void {
      const now = Date.now();
      if (now - lastAttemptAtRef.current < minGapMs) return;
      lastAttemptAtRef.current = now;
      /*
       * A rejected token already cleared the session inside `refreshToken`; a transient failure
       * keeps the current token.
       */
      refreshToken().catch(() => {});
    }

    attempt(0);

    const subscription = AppState.addEventListener(
      "change",
      (status: AppStateStatus) => {
        if (status === "active") attempt(FOREGROUND_MIN_GAP_MS);
      },
    );
    const intervalId = setInterval(() => {
      if (AppState.currentState !== "active") return;
      attempt(INTERVAL_MIN_GAP_MS);
    }, REFRESH_INTERVAL_MS);

    return () => {
      subscription.remove();
      clearInterval(intervalId);
    };
  }, [enabled]);
}
