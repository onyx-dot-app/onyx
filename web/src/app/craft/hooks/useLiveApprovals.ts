"use client";

import useSWR from "swr";

import { fetchLiveApprovals } from "@/app/craft/services/apiServices";
import { ApprovalListResponse } from "@/app/craft/types/approvals";
import { SWR_KEYS } from "@/lib/swr-keys";

// Thin SWR wrapper. Every component that needs to invalidate this list
// can do so with globalMutate on the same SWR key — no callback prop.
export function useLiveApprovals(sessionId: string | null) {
  return useSWR<ApprovalListResponse>(
    sessionId ? SWR_KEYS.buildSessionLiveApprovals(sessionId) : null,
    sessionId ? () => fetchLiveApprovals(sessionId) : null
  );
}
