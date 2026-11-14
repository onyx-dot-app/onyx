// Tool call approvals: what a response's packets say about each request, the status the card shows,
// and the statuses this device learned before the server's resolution packets arrive. Mirrors web's
// lib/chat/toolApprovals.
import { create } from "zustand";

import type { ApprovalDecisionResponse } from "@/api/chat/approvals";
import { getLatestMessageChain, MessageTreeState } from "@/chat/messageTree";
import {
  Packet,
  PacketType,
  ToolApprovalRequest,
  ToolApprovalResolved,
} from "@/chat/streamingModels";

// The send-message error code while a request waits for a decision.
export const APPROVAL_PENDING_ERROR_CODE = "APPROVAL_PENDING";

export type ApprovalDecision = "approve_once" | "approve_session" | "reject";

// "approvedForSession": approved by a grant for the chat's later requests of the same tool.
// "disabled": an approval found the tool disabled, so the call did not run.
// "closed": nothing waits for a decision any more, and the outcome is unknown.
export type ApprovalStatus =
  | "pending"
  | "approved"
  | "approvedForSession"
  | "rejected"
  | "expired"
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
  "rejected",
  "expired",
  "disabled",
  "cancelled",
]);

// A resolution without a known outcome counts as no resolution.
export function readToolApprovals(packets: Packet[]): {
  entries: ToolApprovalEntry[];
  stopped: boolean;
} {
  const entries = new Map<string, ToolApprovalEntry>();
  const outcomes = new Map<string, ToolApprovalResolved["outcome"]>();
  let stopped = false;
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
    } else if (packet.obj.type === PacketType.STOP) {
      stopped = true;
    }
  }
  return {
    entries: Array.from(entries.values(), (entry) => ({
      ...entry,
      outcome: outcomes.get(entry.request.approval_id) ?? null,
    })),
    stopped,
  };
}

// The server's outcome wins. Before it arrives, a decision made here decides it, and a stopped
// response closes it. The device clock never does: the server resolves an expired request.
export function toolApprovalStatus(
  entry: ToolApprovalEntry,
  localStatus: ApprovalStatus | undefined,
  stopped: boolean,
): ApprovalStatus {
  switch (entry.outcome) {
    case null:
      return localStatus ?? (stopped ? "closed" : "pending");
    case "approved_for_chat":
      return "approvedForSession";
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

// The requests of the latest turn that still wait for this user, in order. A failed response's run
// has ended, so its requests wait for nothing; the server's send check expires them.
export function findPendingToolApprovalIds(
  tree: MessageTreeState | undefined,
): string[] {
  if (!tree) return [];
  const chain = getLatestMessageChain(tree);
  const lastUser = chain.findLastIndex((message) => message.type === "user");
  const { localStatuses } = useToolApprovalUi.getState();
  return chain.slice(lastUser + 1).flatMap((response) => {
    if (response.type === "error") return [];
    const { entries, stopped } = readToolApprovals(response.packets);
    return entries
      .filter(
        (entry) =>
          toolApprovalStatus(
            entry,
            localStatuses.get(entry.request.approval_id),
            stopped,
          ) === "pending",
      )
      .map((entry) => entry.request.approval_id);
  });
}

// A card follows the display groups of its own turn and of every earlier turn.
export function orderApprovalsByTurn<G extends { turn_index: number }>(
  displayGroups: G[],
  approvals: ToolApproval[],
): (
  { kind: "display"; group: G } | { kind: "approval"; approval: ToolApproval }
)[] {
  const entries: (
    | { kind: "display"; turnIndex: number; group: G }
    | { kind: "approval"; turnIndex: number; approval: ToolApproval }
  )[] = displayGroups.map((group) => ({
    kind: "display",
    turnIndex: group.turn_index,
    group,
  }));
  for (const approval of approvals) {
    const index = entries.findIndex(
      (entry) => entry.turnIndex > approval.turnIndex,
    );
    entries.splice(index === -1 ? entries.length : index, 0, {
      kind: "approval",
      turnIndex: approval.turnIndex,
      approval,
    });
  }
  return entries;
}
