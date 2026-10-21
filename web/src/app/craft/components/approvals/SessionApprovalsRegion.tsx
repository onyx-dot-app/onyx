"use client";

import useSWR from "swr";
import { useEffect, useRef } from "react";
import isEqual from "lodash/isEqual";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  ApprovalListResponse,
  ApprovalStatusView,
} from "@/app/craft/types/approvals";
import ApprovalCard from "@/app/craft/components/approvals/ApprovalCard";

interface SessionApprovalsRegionProps {
  sessionId: string | null;
}

export default function SessionApprovalsRegion({
  sessionId,
}: SessionApprovalsRegionProps) {
  const { data, mutate } = useSWR<ApprovalListResponse, Error>(
    sessionId ? SWR_KEYS.buildSessionApprovals(sessionId) : null,
    errorHandlingFetcher
  );
  const { data: status } = useSWR<ApprovalStatusView[], Error>(
    sessionId ? SWR_KEYS.buildSessionApprovalStatus(sessionId) : null,
    errorHandlingFetcher,
    { refreshInterval: 10_000 }
  );
  const lastStatus = useRef<{
    sessionId: string | null;
    items: ApprovalStatusView[];
  } | null>(null);
  useEffect(() => {
    if (!status || !data) return;
    const previous = lastStatus.current;
    lastStatus.current = { sessionId, items: status };
    const baseline =
      previous?.sessionId === sessionId
        ? previous.items
        : data.items.map(({ approval_id, decision, is_live }) => ({
            approval_id,
            decision,
            is_live,
          }));
    if (!isEqual(baseline, status)) {
      void mutate();
    }
  }, [status, data, sessionId, mutate]);
  const approvals = [...(data?.items ?? [])].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at)
  );
  if (!sessionId || approvals.length === 0) return null;
  return (
    <div data-testid="session-approvals-region" className="flex flex-col gap-3">
      {approvals.map((approval) => (
        <ApprovalCard
          key={`${approval.approval_id}:${approval.decision ?? "pending"}`}
          approval={approval}
        />
      ))}
    </div>
  );
}
