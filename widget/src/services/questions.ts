/**
 * The agent's questions - status logic and copy for the question card
 */

import type {
  ToolQuestionAnswer,
  ToolQuestionRequest,
  ToolQuestionResolved,
} from "@/types/api-types";
import type { ChatMessage } from "@/types/widget-types";
import {
  type ApprovalEntry,
  holdsChat,
  type LocalApproval,
} from "@/services/approvals";

export interface QuestionEntry {
  request: ToolQuestionRequest;
  /** Null until the resolution packet arrives. */
  resolution: QuestionResolution | null;
}

/**
 * This widget's short-lived state for a question request: its answer is in
 * flight, failed, or got the server's answer ("closed": the request no longer
 * waits, and the outcome is unknown). The resolution packet replaces it.
 */
export type LocalQuestion =
  | "submitting"
  | "failed"
  | "closed"
  | QuestionResolution;

/** One question's choice on the card: a listed option, or "Other" with a note. */
export type QuestionChoice = { option: string } | { note: string };

/** The card's choices of a question request, by question id. */
export type QuestionDraft = Readonly<Record<string, QuestionChoice>>;

/**
 * The draft's choice for a question. Only the draft's own keys count, so a
 * question ID such as "constructor" has no choice until the user makes one.
 */
export function draftChoice(
  draft: QuestionDraft | undefined,
  questionId: string
): QuestionChoice | undefined {
  return draft && Object.prototype.hasOwnProperty.call(draft, questionId)
    ? draft[questionId]
    : undefined;
}

/** A request or question that waits for this user. */
export type PendingWait =
  | { kind: "approval"; entry: ApprovalEntry }
  | { kind: "question"; entry: QuestionEntry };

/** A question's resolution with an outcome that this widget knows. */
export type QuestionResolution = ToolQuestionResolved & {
  outcome: "answered" | "cancelled";
};

/** A resolution with a known outcome, or null for one this widget does not know. */
export function readQuestionResolution(
  value: ToolQuestionResolved
): QuestionResolution | null {
  return value.outcome === "answered" || value.outcome === "cancelled"
    ? { ...value, outcome: value.outcome }
    : null;
}

/**
 * How a question ended, or null while it waits. The resolution packet
 * decides; before it arrives, the server's answer to this widget does.
 */
export function questionResolution(
  entry: QuestionEntry,
  local: LocalQuestion | undefined
): QuestionResolution | null {
  if (entry.resolution !== null) return entry.resolution;
  if (local === "closed") {
    return {
      type: "tool_question_resolved",
      question_request_id: entry.request.question_request_id,
      outcome: "cancelled",
    };
  }
  return typeof local === "object" ? local : null;
}

/**
 * The first request or question that still waits for this user, in
 * transcript order. Subagent requests never hold the chat.
 */
export function findPendingWait(
  messages: ChatMessage[],
  localApprovals: ReadonlyMap<string, LocalApproval>,
  localQuestions: ReadonlyMap<string, LocalQuestion>
): PendingWait | null {
  for (const message of messages) {
    const approval = message.approvals?.find((entry) =>
      holdsChat(entry, localApprovals)
    );
    if (approval) return { kind: "approval", entry: approval };
    const question = message.questions?.find(
      (entry) =>
        questionResolution(
          entry,
          localQuestions.get(entry.request.question_request_id)
        ) === null
    );
    if (question) return { kind: "question", entry: question };
  }
  return null;
}

/**
 * One question's answer, or null while it has no option or an "Other" with
 * an empty note.
 */
export function choiceAnswer(
  questionId: string,
  choice: QuestionChoice | undefined
): ToolQuestionAnswer | null {
  if (!choice) return null;
  if ("option" in choice)
    return { question_id: questionId, option_label: choice.option };
  const note = choice.note.trim();
  return note ? { question_id: questionId, user_note: note } : null;
}

/**
 * The card's answers, one per question in the request's order, or null
 * while a question has no answer.
 */
export function draftAnswers(
  request: ToolQuestionRequest,
  draft: QuestionDraft | undefined
): ToolQuestionAnswer[] | null {
  const answers: ToolQuestionAnswer[] = [];
  for (const question of request.questions) {
    const answer = choiceAnswer(question.id, draftChoice(draft, question.id));
    if (!answer) return null;
    answers.push(answer);
  }
  return answers;
}

/** The one-line records of an ended question request. */
export function questionRecords(
  request: ToolQuestionRequest,
  resolution: QuestionResolution
): string[] {
  const headers = request.questions.map((question) => question.header);
  if (resolution.outcome === "cancelled") {
    return [`No longer waiting: ${headers.join(", ")}`];
  }
  if (resolution.answered_via === "message" || !resolution.answers) {
    return resolution.message
      ? [`Answered in the chat: "${resolution.message}"`]
      : [`Answered in the chat: ${headers.join(", ")}`];
  }
  const answers = new Map(
    resolution.answers.map((answer) => [answer.question_id, answer])
  );
  return request.questions.map((question) => {
    const answer = answers.get(question.id);
    const parts = [answer?.option_label, answer?.user_note?.trim()].filter(
      (part): part is string => !!part
    );
    return `${question.header}: ${parts.length ? parts.join(" - ") : "No answer"}`;
  });
}
