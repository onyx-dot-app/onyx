// Tool call approvals: what a response's packets say about each request, the status the card shows,
// and the statuses this device learned before the server's resolution packets arrive. Mirrors web's
// lib/chat/toolApprovals.
import { create } from "zustand";

import type { ApprovalDecisionResponse } from "@/api/chat/approvals";
import {
  Packet,
  PacketType,
  ToolApprovalRequest,
  ToolApprovalResolved,
} from "@/chat/streamingModels";
import type { ToolCardSpec } from "@/chat/toolCards";

// The send-message error code while a request waits for a decision.
export const APPROVAL_PENDING_ERROR_CODE = "APPROVAL_PENDING";

export type ApprovalDecision = "approve_once" | "approve_session" | "reject";

// "approvedForSession": approved by a grant for the chat's later requests of the same tool.
// "disabled": an approval found the tool disabled, so the call did not run.
// "closed": the request no longer waits for a decision ("cancelled", or a decision answered 404 or
// 409).
export type ApprovalStatus =
  | "pending"
  | "approved"
  | "approvedForSession"
  | "rejected"
  | "disabled"
  | "closed";

export interface ToolApprovalEntry {
  turnIndex: number;
  request: ToolApprovalRequest;
  // Null until the resolution packet arrives.
  outcome: ToolApprovalResolved["outcome"] | null;
}

export interface ToolApproval {
  turnIndex: number;
  request: ToolApprovalRequest;
  status: ApprovalStatus;
}

const OUTCOMES: ReadonlySet<string> = new Set<ToolApprovalResolved["outcome"]>([
  "approved",
  "approved_for_chat",
  "approved_for_command",
  "rejected",
  "disabled",
  "cancelled",
]);

// A resolution without a known outcome counts as no resolution. The server resolves the root
// agent's requests in packets; a subagent's request resolves in a reload of the saved session.
export function readToolApprovals(packets: Packet[]): ToolApprovalEntry[] {
  const entries = new Map<string, ToolApprovalEntry>();
  const outcomes = new Map<string, ToolApprovalResolved["outcome"]>();
  for (const packet of packets) {
    if (packet.obj.type === PacketType.TOOL_APPROVAL_REQUEST) {
      entries.set(packet.obj.approval_id, {
        turnIndex: packet.placement.turn_index,
        request: packet.obj,
        outcome: null,
      });
    } else if (
      packet.obj.type === PacketType.TOOL_APPROVAL_RESOLVED &&
      OUTCOMES.has(packet.obj.outcome)
    ) {
      outcomes.set(packet.obj.approval_id, packet.obj.outcome);
    }
  }
  return Array.from(entries.values(), (entry) => ({
    ...entry,
    outcome: outcomes.get(entry.request.approval_id) ?? null,
  }));
}

// The server's outcome wins. Before it arrives, a decision made here decides it.
export function toolApprovalStatus(
  entry: ToolApprovalEntry,
  localStatus: ApprovalStatus | undefined,
): ApprovalStatus {
  switch (entry.outcome) {
    case null:
      return localStatus ?? "pending";
    case "approved_for_chat":
      return "approvedForSession";
    case "approved_for_command":
      return "approved";
    case "cancelled":
      return "closed";
    default:
      return entry.outcome;
  }
}

// The status the server's answer to a decision made here shows.
export function decidedStatus(
  response: ApprovalDecisionResponse,
): ApprovalStatus {
  if (response.decided_via === "POLICY") return "disabled";
  if (response.decision === "REJECTED") return "rejected";
  return response.decided_via === "SESSION_GRANT"
    ? "approvedForSession"
    : "approved";
}

interface ToolApprovalUiState {
  localStatuses: ReadonlyMap<string, ApprovalStatus>;
  // Bumped when a blocked send points the user at the waiting card.
  nudgeSeq: number;
  // Keeps the status a decision produced until its resolution arrives.
  recordStatus: (approvalId: string, status: ApprovalStatus) => void;
  // Drops statuses that resolution packets now report.
  forgetStatuses: (approvalIds: string[]) => void;
  nudge: () => void;
}

export const useToolApprovalUi = create<ToolApprovalUiState>()((set) => ({
  localStatuses: new Map(),
  nudgeSeq: 0,
  recordStatus: (approvalId, status) =>
    set((state) => ({
      localStatuses: new Map(state.localStatuses).set(approvalId, status),
    })),
  forgetStatuses: (approvalIds) =>
    set((state) => {
      const stale = approvalIds.filter((id) => state.localStatuses.has(id));
      if (stale.length === 0) return {};
      const localStatuses = new Map(state.localStatuses);
      for (const id of stale) localStatuses.delete(id);
      return { localStatuses };
    }),
  nudge: () => set((state) => ({ nudgeSeq: state.nudgeSeq + 1 })),
}));

export const APPROVAL_CARDS: ToolCardSpec<
  ToolApprovalEntry,
  ApprovalStatus,
  ToolApproval
> = {
  read: readToolApprovals,
  id: (entry) => entry.request.approval_id,
  resolved: (entry) => entry.outcome !== null,
  useLocalStatuses: useToolApprovalUi,
  forgetStatuses: (ids) => useToolApprovalUi.getState().forgetStatuses(ids),
  card: (entry, local) => ({
    turnIndex: entry.turnIndex,
    request: entry.request,
    status: toolApprovalStatus(entry, local),
  }),
};
