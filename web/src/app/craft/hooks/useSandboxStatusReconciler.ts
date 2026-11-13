import { useRef } from "react";
import useSWR from "swr";
import {
  useSessionId,
  useSession,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import { fetchSandboxStatus } from "@/app/craft/services/apiServices";
import type { ApiSandboxStatusResponse } from "@/app/craft/types/streamingTypes";

const SANDBOX_STATUS_POLL_INTERVAL_MS = 30_000;
const SANDBOX_PROVISIONING_POLL_INTERVAL_MS = 2_000;

export function useSandboxStatusReconciler(): void {
  const sessionId = useSessionId();
  const session = useSession();
  const updateSessionData = useBuildSessionStore(
    (state) => state.updateSessionData
  );
  const loadSession = useBuildSessionStore((state) => state.loadSession);
  const runtimeStatus = session?.sandbox?.status ?? null;
  const reconcilingSessionIdRef = useRef<string | null>(null);
  // The skill-state revision when the in-flight poll started.
  const pollRevisionRef = useRef<number | null>(null);
  const shouldPoll =
    runtimeStatus === "running" || runtimeStatus === "provisioning";

  useSWR<ApiSandboxStatusResponse, unknown, [string, string] | null>(
    sessionId && shouldPoll ? ["sandbox-status", sessionId] : null,
    ([, id]) => {
      pollRevisionRef.current =
        useBuildSessionStore.getState().sessions.get(id)?.skillsStaleRevision ??
        null;
      return fetchSandboxStatus(id);
    },
    {
      refreshInterval:
        runtimeStatus === "provisioning"
          ? SANDBOX_PROVISIONING_POLL_INTERVAL_MS
          : SANDBOX_STATUS_POLL_INTERVAL_MS,
      onSuccess: (data) => {
        if (!sessionId || data.status === null) return;

        // Read current state instead of the render snapshot: a restore may have
        // started while this request was in flight.
        const current = useBuildSessionStore.getState().sessions.get(sessionId);
        // A push by someone else changes these while the session is open. A
        // poll that started before a newer update (a Reload) does not undo it.
        if (
          current &&
          current.skillsStaleRevision === pollRevisionRef.current &&
          (current.skillsStale !== data.skills_stale ||
            JSON.stringify(current.skillOmissions) !==
              JSON.stringify(data.skill_omissions))
        ) {
          updateSessionData(sessionId, {
            skillsStale: data.skills_stale,
            skillOmissions: data.skill_omissions,
          });
        }
        const sandbox = current?.sandbox;
        if (!sandbox) return;

        // loadSession owns the client-only restoring state until workspace and
        // preview readiness have both been reconciled.
        if (sandbox.status === "restoring" || sandbox.status === data.status) {
          return;
        }

        if (sandbox.status === "provisioning" && data.status === "running") {
          // A running sandbox does not prove that this session's workspace is
          // loaded, so use the workspace-aware session loader.
          if (reconcilingSessionIdRef.current === sessionId) return;
          reconcilingSessionIdRef.current = sessionId;
          void loadSession(sessionId, { force: true }).finally(() => {
            if (reconcilingSessionIdRef.current === sessionId) {
              reconcilingSessionIdRef.current = null;
            }
          });
          return;
        }

        updateSessionData(sessionId, {
          sandbox: { ...sandbox, status: data.status },
        });
      },
    }
  );
}
