/**
 * The tool requests of a chat that wait on the user: approval requests and
 * the questions that the agent asks. Both read from a response's packets,
 * wait in the region after the last message, and leave a record in the
 * reply's timeline once their resolution arrives.
 */
import { create } from "zustand";
import {
  Packet,
  PacketType,
  ToolApprovalRequest,
  ToolApprovalResolved,
  ToolQuestionAnswer,
  ToolQuestionRequest,
  ToolQuestionResolved,
} from "@/app/app/services/streamingModels";
import {
  getLatestMessageChain,
  type MessageTreeState,
} from "@/app/app/services/messageTree";
import { getMultiModelChildren } from "@/lib/timeline/chat/message/multiModel";
import type { Message } from "@/app/app/types";
import type { ApprovalStatus } from "@/lib/approvals/types";
import type { ApprovalDecisionResponse } from "@/lib/chat/types";
import { type CachedRead, readOnce } from "@/lib/chat/packetReads";

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

const approvalReads = new WeakMap<Packet[], CachedRead<ToolApprovalRead>>();
const APPROVAL_PACKETS: ReadonlySet<string> = new Set([
  PacketType.TOOL_APPROVAL_REQUEST,
  PacketType.TOOL_APPROVAL_RESOLVED,
]);

/**
 * The requests in one response's packets and their outcomes. A resolution
 * without a known outcome counts as no resolution. A stop changes nothing:
 * the server resolves every request that it ends, also as "cancelled".
 */
export function readToolApprovals(packets: Packet[]): ToolApprovalRead {
  return readOnce(approvalReads, packets, APPROVAL_PACKETS, (packets) => {
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
    return {
      entries: Array.from(entries.values(), (entry) => ({
        ...entry,
        outcome: outcomes.get(entry.request.approval_id) ?? null,
      })),
    };
  });
}

/** What one response's packets say about a question call. */
export interface ToolQuestionEntry {
  turnIndex: number;
  request: ToolQuestionRequest;
  /** Null until the resolution packet arrives. */
  resolution: ToolQuestionResolved | null;
}

export interface ToolQuestionRead {
  entries: ToolQuestionEntry[];
}

const questionReads = new WeakMap<Packet[], CachedRead<ToolQuestionRead>>();
const QUESTION_PACKETS: ReadonlySet<string> = new Set([
  PacketType.TOOL_QUESTION_REQUEST,
  PacketType.TOOL_QUESTION_RESOLVED,
]);
const QUESTION_OUTCOMES: ReadonlySet<string> = new Set<
  ToolQuestionResolved["outcome"]
>(["answered", "cancelled"]);

/**
 * The question calls in one response's packets and how they ended. As with
 * approvals, only the resolution packet ends a question; a stop does not.
 */
export function readToolQuestions(packets: Packet[]): ToolQuestionRead {
  return readOnce(questionReads, packets, QUESTION_PACKETS, (packets) => {
    const entries = new Map<string, ToolQuestionEntry>();
    const resolutions = new Map<string, ToolQuestionResolved>();
    for (const packet of packets) {
      if (packet.obj.type === PacketType.TOOL_QUESTION_REQUEST) {
        entries.set(packet.obj.question_request_id, {
          turnIndex: packet.placement.turn_index,
          request: packet.obj,
          resolution: null,
        });
      } else if (
        packet.obj.type === PacketType.TOOL_QUESTION_RESOLVED &&
        QUESTION_OUTCOMES.has(packet.obj.outcome)
      ) {
        resolutions.set(packet.obj.question_request_id, packet.obj);
      }
    }
    return {
      entries: Array.from(entries.values(), (entry) => ({
        ...entry,
        resolution: resolutions.get(entry.request.question_request_id) ?? null,
      })),
    };
  });
}

/** Whether the response's packets hold an approval request or a question. */
export function asksUser(packets: Packet[]): boolean {
  return (
    readToolApprovals(packets).entries.length > 0 ||
    readToolQuestions(packets).entries.length > 0
  );
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

/**
 * How a question call shows. "closed": nothing waits for an answer any more,
 * and this client does not know how it ended.
 */
export type ToolQuestionStatus =
  | { kind: "pending" }
  | { kind: "closed" }
  | { kind: "cancelled" }
  | {
      kind: "answered";
      /** The card's answers, in the order of the questions. */
      answers: ToolQuestionAnswer[] | null;
      /** The text that the user typed in the chat instead of the card. */
      message: string | null;
    };

export const PENDING_QUESTION: ToolQuestionStatus = { kind: "pending" };
const CANCELLED_QUESTION: ToolQuestionStatus = { kind: "cancelled" };

/** A question call, as the card or its record shows it. */
export interface ToolQuestionCall {
  turnIndex: number;
  request: ToolQuestionRequest;
  status: ToolQuestionStatus;
}

/**
 * As with approvals, the resolution packet decides the status. Before it
 * arrives, an answer this client sent decides it.
 */
export function toolQuestionStatus(
  entry: ToolQuestionEntry,
  localStatus: ToolQuestionStatus | undefined
): ToolQuestionStatus {
  const { resolution } = entry;
  if (resolution === null) return localStatus ?? PENDING_QUESTION;
  if (resolution.outcome === "cancelled") return CANCELLED_QUESTION;
  return {
    kind: "answered",
    answers: resolution.answers ?? null,
    message: resolution.message ?? null,
  };
}

/** What a reply waits for from its own user, for its timeline header. */
export type AwaitingUser = "approval" | "answer";

/** A request that waits for the user, and the response that holds it. */
export type WaitingToolRequest = {
  turnIndex: number;
  response: Message;
  /** The response is one answer of a multi-model turn. */
  multiModel: boolean;
} & (
  | { kind: "approval"; request: ToolApprovalRequest }
  | { kind: "question"; request: ToolQuestionRequest }
);

/**
 * Every approval request and question on the selected branch that the server
 * has not resolved, the reply's own and its background subagents', oldest
 * response first and by turn within a response.
 */
export function readWaitingToolRequests(
  tree: MessageTreeState
): WaitingToolRequest[] {
  const waiting: WaitingToolRequest[] = [];
  function collect(response: Message, multiModel: boolean) {
    const found: WaitingToolRequest[] = [];
    for (const entry of readToolApprovals(response.packets).entries) {
      if (awaitsDecision(entry))
        found.push({
          kind: "approval",
          turnIndex: entry.turnIndex,
          request: entry.request,
          response,
          multiModel,
        });
    }
    for (const entry of readToolQuestions(response.packets).entries) {
      if (entry.resolution === null)
        found.push({
          kind: "question",
          turnIndex: entry.turnIndex,
          request: entry.request,
          response,
          multiModel,
        });
    }
    // A stable sort keeps packet order within a turn.
    waiting.push(...found.sort((a, b) => a.turnIndex - b.turnIndex));
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

/**
 * The question calls on the selected branch that the server has not
 * resolved, oldest first, each with the status that this client knows. A
 * question that this client already answered, or found closed, keeps its
 * local status until the resolution arrives; only a pending one still
 * waits for the user's answer.
 */
export function readWaitingQuestions(
  tree: MessageTreeState,
  localAnswers: ReadonlyMap<string, ToolQuestionStatus>
): ToolQuestionCall[] {
  return readWaitingToolRequests(tree).flatMap((item) =>
    item.kind === "question"
      ? [
          {
            turnIndex: item.turnIndex,
            request: item.request,
            status:
              localAnswers.get(item.request.question_request_id) ??
              PENDING_QUESTION,
          },
        ]
      : []
  );
}

/**
 * The record of an approval request or a question call in a reply's
 * timeline.
 */
export type ToolRequestRecord =
  | ({ kind: "approval" } & ToolApproval)
  | ({ kind: "question" } & ToolQuestionCall);

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

interface ToolRequestUiState {
  /** Approval statuses this client learned before the resolution packets
   * arrive. */
  localStatuses: ReadonlyMap<string, ApprovalStatus>;
  /** Question statuses this client learned before the resolution packets
   * arrive. */
  localAnswers: ReadonlyMap<string, ToolQuestionStatus>;
  /** The card to bring into view, by approval or question request ID; `seq`
   * repeats the nudge for the same card. */
  nudge: { requestId: string; seq: number } | null;
  /** Records the status a decision produced until its resolution arrives. */
  recordStatus: (approvalId: string, status: ApprovalStatus) => void;
  /** Records the status an answer produced until its resolution arrives. */
  recordAnswer: (questionRequestId: string, status: ToolQuestionStatus) => void;
  /** Drops statuses that resolution packets now report. */
  forgetStatuses: (requestIds: string[]) => void;
  nudgeRequest: (requestId: string) => void;
  /** Called once the card handled the nudge, so a remount does not repeat it. */
  clearNudge: (seq: number) => void;
}

export const useToolRequestUi = create<ToolRequestUiState>()((set, get) => ({
  localStatuses: new Map(),
  localAnswers: new Map(),
  nudge: null,
  recordStatus: (approvalId, status) =>
    set((state) => ({
      localStatuses: new Map(state.localStatuses).set(approvalId, status),
    })),
  recordAnswer: (questionRequestId, status) =>
    set((state) => ({
      localAnswers: new Map(state.localAnswers).set(questionRequestId, status),
    })),
  forgetStatuses: (requestIds) =>
    set((state) => {
      const update: Partial<ToolRequestUiState> = {};
      if (requestIds.some((id) => state.localStatuses.has(id))) {
        const localStatuses = new Map(state.localStatuses);
        for (const id of requestIds) localStatuses.delete(id);
        update.localStatuses = localStatuses;
      }
      if (requestIds.some((id) => state.localAnswers.has(id))) {
        const localAnswers = new Map(state.localAnswers);
        for (const id of requestIds) localAnswers.delete(id);
        update.localAnswers = localAnswers;
      }
      return update;
    }),
  nudgeRequest: (requestId) => {
    const seq = ++lastNudgeSeq;
    set({ nudge: { requestId, seq } });
    setTimeout(() => get().clearNudge(seq), NUDGE_TTL_MS);
  },
  clearNudge: (seq) =>
    set((state) => (state.nudge?.seq === seq ? { nudge: null } : {})),
}));
