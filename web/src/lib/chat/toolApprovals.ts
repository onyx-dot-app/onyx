import { create } from "zustand";
import {
  Packet,
  PacketType,
  ToolApprovalRequest,
  ToolApprovalResolved,
} from "@/app/app/services/streamingModels";
import {
  getLatestTurn,
  type MessageTreeState,
} from "@/app/app/services/messageTree";
import type { ApprovalStatus } from "@/lib/approvals/types";
import type { GroupedPacket } from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";
import type { ApprovalDecisionResponse } from "@/lib/chat/types";

/** What one response's packets say about an approval request. */
export interface ToolApprovalEntry {
  turnIndex: number;
  request: ToolApprovalRequest;
  /** Null until the resolution packet arrives. */
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

/**
 * The requests in one response's packets, and whether the response stopped.
 * A resolution without a known outcome counts as no resolution. The stop that
 * closes a lost stream is this client's own, so it does not count: the server
 * can still wait for a decision.
 */
export function readToolApprovals(
  packets: Packet[],
  streamLost = false
): {
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
    } else if (packet.obj.type === PacketType.STOP && !streamLost) {
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

/**
 * The resolution packet decides the status. Before it arrives, a decision this
 * client made decides it; a stopped response closes the request. The deadline
 * never does: the server resolves an expired request.
 */
export function toolApprovalStatus(
  entry: ToolApprovalEntry,
  localStatus: ApprovalStatus | undefined,
  stopped: boolean
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

export type SectionEntry =
  | { kind: "display"; turnIndex: number; group: GroupedPacket }
  | { kind: "approval"; turnIndex: number; approval: ToolApproval };

/**
 * Orders approval cards with a section's display groups by turn. A card
 * follows the display groups of its own turn and of every earlier turn.
 */
export function orderApprovalsByTurn(
  displayGroups: GroupedPacket[],
  approvals: ToolApproval[]
): SectionEntry[] {
  const entries: SectionEntry[] = displayGroups.map((group) => ({
    kind: "display",
    turnIndex: group.turn_index,
    group,
  }));
  for (const approval of approvals) {
    const index = entries.findIndex(
      (entry) => entry.turnIndex > approval.turnIndex
    );
    entries.splice(index === -1 ? entries.length : index, 0, {
      kind: "approval",
      turnIndex: approval.turnIndex,
      approval,
    });
  }
  return entries;
}

/** The status the server's answer to this client's decision shows. */
export function decidedStatus(
  response: ApprovalDecisionResponse
): ApprovalStatus {
  if (response.decided_via === "POLICY") return "disabled";
  if (response.decision === "REJECTED") return "rejected";
  return response.decided_via === "SESSION_GRANT"
    ? "approvedForSession"
    : "approved";
}

// A nudge whose card is not on screen is dropped instead of firing later.
const NUDGE_TTL_MS = 2000;
let lastNudgeSeq = 0;

interface ToolApprovalUiState {
  /** Statuses this client learned before the resolution packets arrive. */
  localStatuses: ReadonlyMap<string, ApprovalStatus>;
  /** The card to bring into view; `seq` repeats the nudge for the same card. */
  nudge: { approvalId: string; seq: number } | null;
  /** Records the status a decision produced until its resolution arrives. */
  recordStatus: (approvalId: string, status: ApprovalStatus) => void;
  /** Drops statuses that resolution packets now report. */
  forgetStatuses: (approvalIds: string[]) => void;
  nudgeApproval: (approvalId: string) => void;
  /** Called once the card handled the nudge, so a remount does not repeat it. */
  clearNudge: (seq: number) => void;
}

export const useToolApprovalUi = create<ToolApprovalUiState>()((set, get) => ({
  localStatuses: new Map(),
  nudge: null,
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
  nudgeApproval: (approvalId) => {
    const seq = ++lastNudgeSeq;
    set({ nudge: { approvalId, seq } });
    setTimeout(() => get().clearNudge(seq), NUDGE_TTL_MS);
  },
  clearNudge: (seq) =>
    set((state) => (state.nudge?.seq === seq ? { nudge: null } : {})),
}));

/** The first request of the latest turn that still waits for this user. */
export function findPendingToolApprovalId(
  tree: MessageTreeState | undefined
): string | null {
  if (!tree) return null;
  const { localStatuses } = useToolApprovalUi.getState();
  for (const response of getLatestTurn(tree)) {
    const { entries, stopped } = readToolApprovals(
      response.packets,
      response.streamLost
    );
    const pending = entries.find(
      (entry) =>
        toolApprovalStatus(
          entry,
          localStatuses.get(entry.request.approval_id),
          stopped
        ) === "pending"
    );
    if (pending) return pending.request.approval_id;
  }
  return null;
}
