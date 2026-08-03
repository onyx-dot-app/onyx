import { useRef } from "react";
import useSWR from "swr";
import {
  useSessionId,
  useSession,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import { fetchSandboxStatus } from "@/app/craft/services/apiServices";
import { ApiSandboxStatusResponse } from "@/app/craft/types/streamingTypes";

export const SANDBOX_STATUS_POLL_INTERVAL_MS = 30_000;
export const SANDBOX_PROVISIONING_POLL_INTERVAL_MS = 2_000;

export function useSandboxSleepWatcher(): void {
  const sessionId = useSessionId();
  const session = useSession();
  const updateSessionData = useBuildSessionStore(
    (state) => state.updateSessionData
  );
  const loadSession = useBuildSessionStore((state) => state.loadSession);
  const status = session?.sandbox?.status ?? null;
  const reconcilingSessionIdRef = useRef<string | null>(null);
  const shouldPoll = status === "running" || status === "provisioning";

  useSWR<ApiSandboxStatusResponse, unknown, [string, string] | null>(
    sessionId && shouldPoll ? ["sandbox-status", sessionId] : null,
    ([, id]) => fetchSandboxStatus(id),
    {
      refreshInterval:
        status === "provisioning"
          ? SANDBOX_PROVISIONING_POLL_INTERVAL_MS
          : SANDBOX_STATUS_POLL_INTERVAL_MS,
      onSuccess: (data) => {
        if (!sessionId || data.status === null) return;
        // Use onSuccess (not a useEffect over `data`) — SWR can serve a stale
        // cached "sleeping"/"terminated" result right when a key re-activates
        // (e.g. after a wake flips status back to running), and an effect
        // over `data` would re-apply that stale value and wedge the UI.
        const sandbox = useBuildSessionStore
          .getState()
          .sessions.get(sessionId)?.sandbox;
        if (!sandbox) return;

        if (sandbox.status === "provisioning" && data.status === "running") {
          // A running sandbox does not prove this session's workspace exists.
          // Re-run the workspace-aware load so it restores the session when
          // another request was responsible for provisioning the sandbox.
          if (reconcilingSessionIdRef.current === sessionId) return;
          reconcilingSessionIdRef.current = sessionId;
          void loadSession(sessionId, { force: true }).finally(() => {
            if (reconcilingSessionIdRef.current === sessionId) {
              reconcilingSessionIdRef.current = null;
            }
          });
          return;
        }

        // loadSession owns the frontend-only restoring state until it has
        // reconciled the workspace and preview readiness.
        if (sandbox.status === "restoring") return;
        if (sandbox.status === data.status) return;
        updateSessionData(sessionId, {
          sandbox: { ...sandbox, status: data.status },
        });
      },
    }
  );
}
