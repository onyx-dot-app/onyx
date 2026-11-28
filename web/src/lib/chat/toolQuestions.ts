/**
 * The questions that the agent asks the user: how one response's packets
 * show them and how a question call shows.
 */
import {
  Packet,
  PacketType,
  ToolQuestionAnswer,
  ToolQuestionRequest,
  ToolQuestionResolved,
} from "@/app/app/services/streamingModels";
import { type CachedRead, readOnce } from "@/lib/chat/packetReads";

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
