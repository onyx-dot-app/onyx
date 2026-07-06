import { useEffect, useRef } from "react";
import {
  useSessionId,
  useSession,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import { fetchSandboxStatus } from "@/app/craft/services/apiServices";
import { ApiSandboxStatusResponse } from "@/app/craft/types/streamingTypes";

// Fallback when cached sandbox data predates idle_cleanup_interval_seconds.
export const DEFAULT_CLEANUP_INTERVAL_SECONDS = 60;
// Margin past one full reaper sweep so an in-progress sweep can finish.
export const SLEEP_SLACK_BUFFER_MS = 30_000;
export const RETRY_DELAY_MS = 60_000;
const RECHECK_THROTTLE_MS = 30_000;

function sweepMs(cleanupIntervalSeconds: number | null | undefined): number {
  return (cleanupIntervalSeconds ?? DEFAULT_CLEANUP_INTERVAL_SECONDS) * 1000;
}

export function computeSleepDeadlineMs(
  lastHeartbeat: string | null,
  createdAt: string | null,
  idleTimeoutSeconds: number,
  cleanupIntervalSeconds: number | null,
  nowMs: number
): number {
  const idleSince = lastHeartbeat ?? createdAt;
  const heartbeatMs = idleSince ? Date.parse(idleSince) : nowMs;
  return (
    heartbeatMs +
    idleTimeoutSeconds * 1000 +
    sweepMs(cleanupIntervalSeconds) +
    SLEEP_SLACK_BUFFER_MS
  );
}

export function useSandboxSleepWatcher(): void {
  const sessionId = useSessionId();
  const session = useSession();
  const updateSessionData = useBuildSessionStore(
    (state) => state.updateSessionData
  );
  const sandbox = session?.sandbox ?? null;
  const status = sandbox?.status ?? null;
  const lastHeartbeat = sandbox?.last_heartbeat ?? null;
  const createdAt = sandbox?.created_at ?? null;

  const lastRecheckRef = useRef(0);

  useEffect(() => {
    if (!sessionId || status !== "running") return;

    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    let retried = false;
    let inFlight = false;

    const applyResult = (result: ApiSandboxStatusResponse) => {
      const currentSandbox = useBuildSessionStore
        .getState()
        .sessions.get(sessionId)?.sandbox;
      if (!currentSandbox) return;

      if (result.status === "sleeping" || result.status === "terminated") {
        updateSessionData(sessionId, {
          sandbox: { ...currentSandbox, status: result.status },
        });
        return;
      }

      if (result.status === "running") {
        updateSessionData(sessionId, {
          sandbox: {
            ...currentSandbox,
            last_heartbeat: result.last_heartbeat,
            idle_timeout_seconds: result.idle_timeout_seconds,
            idle_cleanup_interval_seconds: result.idle_cleanup_interval_seconds,
          },
        });
      }
    };

    const check = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const result = await fetchSandboxStatus(sessionId);
        if (cancelled) return;
        applyResult(result);
        retried = false;
        // Re-arm here: an unchanged heartbeat won't re-run the effect, so
        // relying on the dep change alone would leave the watcher dormant.
        if (result.status === "running") {
          const deadline = computeSleepDeadlineMs(
            result.last_heartbeat,
            result.created_at,
            result.idle_timeout_seconds,
            result.idle_cleanup_interval_seconds,
            Date.now()
          );
          const overdueDelay = Math.max(
            sweepMs(result.idle_cleanup_interval_seconds),
            RETRY_DELAY_MS
          );
          timeoutId = setTimeout(
            check,
            deadline > Date.now() ? deadline - Date.now() : overdueDelay
          );
        }
      } catch (err) {
        console.warn("Sandbox sleep check failed:", err);
        if (cancelled || retried) return;
        retried = true;
        timeoutId = setTimeout(check, RETRY_DELAY_MS);
      } finally {
        inFlight = false;
      }
    };

    const arm = async () => {
      let idleTimeoutSeconds = sandbox?.idle_timeout_seconds;
      let cleanupIntervalSeconds =
        sandbox?.idle_cleanup_interval_seconds ?? null;
      let heartbeat = lastHeartbeat;

      if (idleTimeoutSeconds == null) {
        try {
          const result = await fetchSandboxStatus(sessionId);
          if (cancelled) return;
          applyResult(result);
          idleTimeoutSeconds = result.idle_timeout_seconds;
          cleanupIntervalSeconds = result.idle_cleanup_interval_seconds;
          heartbeat = result.last_heartbeat;
          if (result.status !== "running") return;
        } catch (err) {
          console.warn("Sandbox sleep watcher failed to arm:", err);
          if (!cancelled) timeoutId = setTimeout(arm, RETRY_DELAY_MS);
          return;
        }
      }

      const deadline = computeSleepDeadlineMs(
        heartbeat,
        createdAt,
        idleTimeoutSeconds,
        cleanupIntervalSeconds,
        Date.now()
      );
      timeoutId = setTimeout(check, Math.max(deadline - Date.now(), 0));
    };

    const recheckThrottled = () => {
      const now = Date.now();
      if (now - lastRecheckRef.current < RECHECK_THROTTLE_MS) return;
      lastRecheckRef.current = now;
      if (timeoutId) clearTimeout(timeoutId);
      check();
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible") recheckThrottled();
    };
    const onOnline = () => recheckThrottled();

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", onOnline);

    arm();

    return () => {
      cancelled = true;
      if (timeoutId) clearTimeout(timeoutId);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", onOnline);
    };
  }, [sessionId, status, lastHeartbeat, createdAt, updateSessionData]);
}
