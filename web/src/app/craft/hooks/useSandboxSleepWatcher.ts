import useSWR from "swr";
import {
  useSessionId,
  useSession,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import { fetchSandboxStatus } from "@/app/craft/services/apiServices";
import { ApiSandboxStatusResponse } from "@/app/craft/types/streamingTypes";

export const SANDBOX_STATUS_POLL_INTERVAL_MS = 30_000;

export function useSandboxSleepWatcher(): void {
  const sessionId = useSessionId();
  const session = useSession();
  const updateSessionData = useBuildSessionStore(
    (state) => state.updateSessionData
  );
  const status = session?.sandbox?.status ?? null;

  useSWR<ApiSandboxStatusResponse, unknown, [string, string] | null>(
    sessionId && status === "running" ? ["sandbox-status", sessionId] : null,
    ([, id]) => fetchSandboxStatus(id),
    {
      refreshInterval: SANDBOX_STATUS_POLL_INTERVAL_MS,
      onSuccess: (data) => {
        if (!sessionId) return;
        if (data.status !== "sleeping" && data.status !== "terminated") return;
        // Use onSuccess (not a useEffect over `data`) — SWR can serve a stale
        // cached "sleeping"/"terminated" result right when a key re-activates
        // (e.g. after a wake flips status back to running), and an effect
        // over `data` would re-apply that stale value and wedge the UI.
        const sandbox = useBuildSessionStore
          .getState()
          .sessions.get(sessionId)?.sandbox;
        if (sandbox && sandbox.status === "running") {
          updateSessionData(sessionId, {
            sandbox: { ...sandbox, status: data.status },
          });
        }
      },
    }
  );
}
