import { useCallback, useRef } from "react";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";

interface WakeIntentEvent {
  key?: string;
  shiftKey?: boolean;
  preventDefault: () => void;
  stopPropagation: () => void;
}

export function useWakeOnIntent(): (event?: WakeIntentEvent) => void {
  const inFlightRef = useRef(false);

  return useCallback((event?: WakeIntentEvent) => {
    const { currentSessionId, sessions, loadSession } =
      useBuildSessionStore.getState();
    const status = currentSessionId
      ? (sessions.get(currentSessionId)?.sandbox?.status ?? null)
      : null;

    if (status !== "sleeping" && status !== "terminated") return;

    // A submitting Enter must not race the wake: the store only flips to
    // "restoring" after loadSession's first await, so without this the same
    // keydown would reach the submit path while the sandbox is un-restored.
    if (event?.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.stopPropagation();
    }

    if (!currentSessionId || inFlightRef.current) return;

    inFlightRef.current = true;
    void Promise.resolve(
      loadSession(currentSessionId, { force: true })
    ).finally(() => {
      inFlightRef.current = false;
    });
  }, []);
}
