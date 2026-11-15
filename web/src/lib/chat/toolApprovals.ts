import { create } from "zustand";
import {
  Packet,
  PacketType,
  ToolApprovalRequest,
  ToolApprovalResolved,
} from "@/app/app/services/streamingModels";
import {
  getLatestMessageChain,
  type MessageTreeState,
} from "@/app/app/services/messageTree";
import { getMultiModelChildren } from "@/app/app/message/multiModel";
import type { Message } from "@/app/app/types";
import type { ApprovalStatus } from "@/lib/approvals/types";
import type { GroupedPacket } from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";
import type {
  ApprovalDecisionResponse,
  ChatSessionStatus,
} from "@/lib/chat/types";

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
  "disabled",
  "cancelled",
]);

export interface ToolApprovalRead {
  entries: ToolApprovalEntry[];
}

// Streams append to a response's packet array and a replay replaces it, so a
// read stays valid for the same array until it grows.
const approvalReads = new WeakMap<
  Packet[],
  { count: number; read: ToolApprovalRead }
>();

/**
 * The requests in one response's packets and their outcomes. A resolution
 * without a known outcome counts as no resolution. A stop changes nothing:
 * the server resolves every request that it ends, also as "cancelled".
 * Packets that cannot change the result keep the same read object.
 */
export function readToolApprovals(packets: Packet[]): ToolApprovalRead {
  const cached = approvalReads.get(packets);
  if (cached && cached.count <= packets.length) {
    let changed = false;
    for (
      let index = cached.count;
      index < packets.length && !changed;
      index++
    ) {
      const type = packets[index]?.obj.type;
      changed =
        type === PacketType.TOOL_APPROVAL_REQUEST ||
        type === PacketType.TOOL_APPROVAL_RESOLVED;
    }
    if (!changed) {
      cached.count = packets.length;
      return cached.read;
    }
  }
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
  const read: ToolApprovalRead = {
    entries: Array.from(entries.values(), (entry) => ({
      ...entry,
      outcome: outcomes.get(entry.request.approval_id) ?? null,
    })),
  };
  approvalReads.set(packets, { count: packets.length, read });
  return read;
}

/** Whether the server still waits for a decision on the request. */
export function awaitsDecision(entry: ToolApprovalEntry): boolean {
  return entry.outcome === null;
}

/**
 * The resolution packet decides the status. Before it arrives, a decision this
 * client made decides it.
 */
export function toolApprovalStatus(
  entry: ToolApprovalEntry,
  localStatus: ApprovalStatus | undefined
): ApprovalStatus {
  switch (entry.outcome) {
    case null:
      return localStatus ?? "pending";
    case "approved_for_chat":
      return "approvedForSession";
    case "cancelled":
      return "closed";
    default:
      return entry.outcome;
  }
}

/** A request that waits for a decision, and the response that holds it. */
interface WaitingToolApproval {
  turnIndex: number;
  request: ToolApprovalRequest;
  response: Message;
  /** The response is one answer of a multi-model turn. */
  multiModel: boolean;
}

/**
 * Every request on the selected branch that the server has not resolved, the
 * reply's own and its background subagents', oldest response first and in
 * packet order within a response.
 */
export function readWaitingToolApprovals(
  tree: MessageTreeState
): WaitingToolApproval[] {
  const waiting: WaitingToolApproval[] = [];
  function collect(response: Message, multiModel: boolean) {
    for (const entry of readToolApprovals(response.packets).entries) {
      if (awaitsDecision(entry))
        waiting.push({
          turnIndex: entry.turnIndex,
          request: entry.request,
          response,
          multiModel,
        });
    }
  }
  let multiModelQuestion: number | null = null;
  for (const message of getLatestMessageChain(tree)) {
    if (message.type === "user") {
      const answers = getMultiModelChildren(message, tree);
      multiModelQuestion = answers ? message.nodeId : null;
      for (const answer of answers ?? []) collect(answer, true);
    } else if (
      (message.type === "assistant" || message.type === "error") &&
      message.parentNodeId !== multiModelQuestion
    ) {
      collect(message, false);
    }
  }
  return waiting;
}

type SectionEntry =
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

/**
 * Status reads after a decision on a background agent's request. The decision
 * starts no stream, and the agent resumes in an agent host that starts after
 * the decision returns, so its later requests show only after a reload.
 */
export interface AgentWatch {
  sessionId: string;
  reads: number;
  /** A read saw the chat's background agents run. */
  sawRunning: boolean;
}

/** Reads that end a watch whose agents never showed as running. */
export const AGENT_WATCH_GRACE_READS = 5;

/**
 * The watch after one status read, or null once it ends: the agents ran and
 * settled, or they never ran within the grace reads.
 */
export function nextAgentWatch(
  watch: AgentWatch,
  status: Pick<ChatSessionStatus, "has_active_subagents">
): AgentWatch | null {
  const reads = watch.reads + 1;
  if (status.has_active_subagents) return { ...watch, reads, sawRunning: true };
  if (watch.sawRunning || reads >= AGENT_WATCH_GRACE_READS) return null;
  return { ...watch, reads };
}

// A nudge whose card is not on screen is dropped instead of firing later.
const NUDGE_TTL_MS = 2000;
let lastNudgeSeq = 0;

interface ToolApprovalUiState {
  /** Statuses this client learned before the resolution packets arrive. */
  localStatuses: ReadonlyMap<string, ApprovalStatus>;
  /** The card to bring into view; `seq` repeats the nudge for the same card. */
  nudge: { approvalId: string; seq: number } | null;
  agentWatch: AgentWatch | null;
  /** Records the status a decision produced until its resolution arrives. */
  recordStatus: (approvalId: string, status: ApprovalStatus) => void;
  /** Drops statuses that resolution packets now report. */
  forgetStatuses: (approvalIds: string[]) => void;
  nudgeApproval: (approvalId: string) => void;
  /** Called once the card handled the nudge, so a remount does not repeat it. */
  clearNudge: (seq: number) => void;
  /** Starts a watch, which replaces any earlier one. */
  watchAgents: (sessionId: string) => void;
  /** Applies a status read of the chat to its watch. */
  noteAgentStatus: (
    sessionId: string,
    status: Pick<ChatSessionStatus, "has_active_subagents">
  ) => void;
}

export const useToolApprovalUi = create<ToolApprovalUiState>()((set, get) => ({
  localStatuses: new Map(),
  nudge: null,
  agentWatch: null,
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
  watchAgents: (sessionId) =>
    set({ agentWatch: { sessionId, reads: 0, sawRunning: false } }),
  noteAgentStatus: (sessionId, status) =>
    set((state) =>
      state.agentWatch?.sessionId === sessionId
        ? { agentWatch: nextAgentWatch(state.agentWatch, status) }
        : {}
    ),
}));
