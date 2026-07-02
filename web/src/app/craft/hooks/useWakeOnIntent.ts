import { useCallback, useRef } from "react";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";

export function useWakeOnIntent(): () => void {
  const inFlightRef = useRef(false);

  return useCallback(() => {
    const { currentSessionId, sessions, loadSession } =
      useBuildSessionStore.getState();
    const status = currentSessionId
      ? (sessions.get(currentSessionId)?.sandbox?.status ?? null)
      : null;

    if (status !== "sleeping" && status !== "terminated") {
      inFlightRef.current = false;
      return;
    }

    if (!currentSessionId || inFlightRef.current) return;

    inFlightRef.current = true;
    void loadSession(currentSessionId, { force: true });
  }, []);
}
