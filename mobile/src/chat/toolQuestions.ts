// The questions that the agent asks the user: what a response's packets say about each request, and
// the resolutions this device learned before the server's resolution packets arrive. The card
// answers each question with one option or an "Other" note; a message that the user types in the
// chat while a question waits answers every question of that response.
import { create } from "zustand";

import type { Message } from "@/chat/interfaces";
import {
  Packet,
  PacketType,
  ToolQuestionRequest,
  ToolQuestionResolved,
} from "@/chat/streamingModels";
import type { ToolCardSpec } from "@/chat/toolCards";

export type QuestionResolution = Pick<
  ToolQuestionResolved,
  "outcome" | "answered_via" | "answers" | "message"
>;

export interface ToolQuestionEntry {
  turnIndex: number;
  request: ToolQuestionRequest;
  // Null until the resolution packet arrives.
  resolved: ToolQuestionResolved | null;
}

export interface ToolQuestion {
  turnIndex: number;
  request: ToolQuestionRequest;
  // Null while the question waits.
  resolution: QuestionResolution | null;
}

// A question that no longer waits for an answer from this device (404 or 409).
export const CLOSED_QUESTION: QuestionResolution = { outcome: "cancelled" };

const OUTCOMES: ReadonlySet<string> = new Set<ToolQuestionResolved["outcome"]>([
  "answered",
  "cancelled",
]);

// A resolution without a known outcome counts as no resolution.
export function readToolQuestions(packets: Packet[]): ToolQuestionEntry[] {
  const entries = new Map<string, ToolQuestionEntry>();
  const resolutions = new Map<string, ToolQuestionResolved>();
  for (const packet of packets) {
    if (packet.obj.type === PacketType.TOOL_QUESTION_REQUEST) {
      entries.set(packet.obj.question_request_id, {
        turnIndex: packet.placement.turn_index,
        request: packet.obj,
        resolved: null,
      });
    } else if (
      packet.obj.type === PacketType.TOOL_QUESTION_RESOLVED &&
      OUTCOMES.has(packet.obj.outcome)
    ) {
      resolutions.set(packet.obj.question_request_id, packet.obj);
    }
  }
  return Array.from(entries.values(), (entry) => ({
    ...entry,
    resolved: resolutions.get(entry.request.question_request_id) ?? null,
  }));
}

// The IDs of the questions that the last reply of a message chain shows waiting. A message sent
// from the composer answers them.
export function waitingQuestionIds(
  chain: Message[],
  localStatuses: ReadonlyMap<string, QuestionResolution>,
): string[] {
  const reply = chain.at(-1);
  if (reply?.type !== "assistant") return [];
  return readToolQuestions(reply.packets)
    .filter(
      (entry) =>
        entry.resolved === null &&
        !localStatuses.has(entry.request.question_request_id),
    )
    .map((entry) => entry.request.question_request_id);
}

// One typed message answers every waiting question of the response, so calls of one turn that it
// answered show it once, after the last of them.
export function typedAnswerShownBy(questions: ToolQuestion[]): Set<string> {
  const shown = new Set<string>();
  questions.forEach((question, index) => {
    const { resolution } = question;
    if (resolution?.answered_via !== "message") return;
    const next = questions[index + 1];
    if (
      next?.turnIndex === question.turnIndex &&
      next.resolution?.answered_via === "message" &&
      next.resolution.message === resolution.message
    )
      return;
    shown.add(question.request.question_request_id);
  });
  return shown;
}

interface ToolQuestionUiState {
  localStatuses: ReadonlyMap<string, QuestionResolution>;
  // Keeps the resolution that an answer from this device produced until its packet arrives. A
  // question that already has one keeps it: the card and the composer can race, and the answer
  // that the server took came first.
  recordStatuses: (
    questionRequestIds: string[],
    resolution: QuestionResolution,
  ) => void;
  // Drops resolutions that resolution packets now report.
  forgetStatuses: (questionRequestIds: string[]) => void;
  // Drops every resolution, with the answers it holds, when the account changes.
  reset: () => void;
}

export const useToolQuestionUi = create<ToolQuestionUiState>()((set) => ({
  localStatuses: new Map(),
  recordStatuses: (questionRequestIds, resolution) =>
    set((state) => {
      const open = questionRequestIds.filter(
        (id) => !state.localStatuses.has(id),
      );
      if (open.length === 0) return {};
      const localStatuses = new Map(state.localStatuses);
      for (const id of open) localStatuses.set(id, resolution);
      return { localStatuses };
    }),
  forgetStatuses: (questionRequestIds) =>
    set((state) => {
      const stale = questionRequestIds.filter((id) =>
        state.localStatuses.has(id),
      );
      if (stale.length === 0) return {};
      const localStatuses = new Map(state.localStatuses);
      for (const id of stale) localStatuses.delete(id);
      return { localStatuses };
    }),
  reset: () => set({ localStatuses: new Map() }),
}));

// The server's resolution wins; before it arrives, an answer from this device resolves it.
export const QUESTION_CARDS: ToolCardSpec<
  ToolQuestionEntry,
  QuestionResolution,
  ToolQuestion
> = {
  read: readToolQuestions,
  id: (entry) => entry.request.question_request_id,
  resolved: (entry) => entry.resolved !== null,
  useLocalStatuses: useToolQuestionUi,
  forgetStatuses: (ids) => useToolQuestionUi.getState().forgetStatuses(ids),
  card: (entry, local) => ({
    turnIndex: entry.turnIndex,
    request: entry.request,
    resolution: entry.resolved ?? local ?? null,
  }),
};
