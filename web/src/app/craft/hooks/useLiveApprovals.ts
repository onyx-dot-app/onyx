"use client";

import useSWR from "swr";

import { fetchLiveApprovals } from "@/app/craft/services/apiServices";
import { ApprovalListResponse } from "@/app/craft/types/approvals";
import { SWR_KEYS } from "@/lib/swr-keys";

// How often to re-check /live for server-side state changes the client
// has no streaming signal for: an approval expiring (180s server cap),
// being decided by another device, or being decided by a collaborator.
// New approvals already arrive via the `approval_requested` packet path,
// so this poll is the "catch removals" loop, not the primary signal.
const LIVE_APPROVALS_REFRESH_MS = 10_000;

// Thin SWR wrapper. Every component that needs to invalidate this list
// can do so with globalMutate on the same SWR key — no callback prop.
export function useLiveApprovals(sessionId: string | null) {
  return useSWR<ApprovalListResponse>(
    sessionId ? SWR_KEYS.buildSessionLiveApprovals(sessionId) : null,
    sessionId ? () => fetchLiveApprovals(sessionId) : null,
    {
      refreshInterval: LIVE_APPROVALS_REFRESH_MS,
    }
  );
}
