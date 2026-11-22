import type { ChatStream, Message } from "@/app/app/types";
import type { LLMOverride } from "@/app/app/services/lib";
import type { ToolQuestionAnswer } from "@/app/app/services/streamingModels";
import type { ProjectFile } from "@/lib/projects/types";

/** A chat skill the user picked with `@`, by name. */
export interface SkillMention {
  type: "skill";
  name: string;
}

/** What the user tagged in a message with `@`. Mirrors `Mention` in
 * `backend/onyx/chat/mention_models.py`: each kind is one member of the union
 * on `type`, and skills are the only kind. */
export type Mention = SkillMention;

/** The most distinct mentions one message can send. Mirrors
 * `MAX_MENTIONS_PER_MESSAGE` in `backend/onyx/chat/mention_models.py`. */
export const MAX_MENTIONS_PER_MESSAGE = 20;

/** A picked skill at the version the user ran when its question was
 * accepted. */
export interface RecordedSkillMention extends SkillMention {
  version_id: string;
}

/** A mention as its question's turn resolved it. Mirrors `RecordedMention`
 * in `backend/onyx/chat/mention_models.py`. */
export type RecordedMention = RecordedSkillMention;

/** A mention as a question holds it: one per picked tile, with `index`, where
 * its `@name` starts in the message. A mention known only from the server,
 * such as a recorded or queued one, has no `index`. The server gets each
 * mention once, without `index` (`lib/chat/mentions.ts:requestMentions`). */
export type ComposedMention = Mention & { index?: number };

/** A mention at a known place in its message. */
export type PlacedMention = Mention & { index: number };

/** A question as the user wrote it: its text and what the user tagged in it.
 * Mentions come only from the `@` menu; the text holds an `@name` for each,
 * and plain `@name` text mentions nothing. */
export interface ComposedMessage {
  message: string;
  mentions: ComposedMention[];
}

/** A question that did not reach the server, to put back in the composer. */
export interface UnsentMessage extends ComposedMessage {
  files: ProjectFile[];
}

/** Composer choices that a queued or interrupting message's turn starts with. */
export interface PendingTurnSettings {
  deepResearch: boolean;
  /** Null uses the chat's saved model. */
  llmOverride: LLMOverride | null;
}

export interface PendingChatMessage {
  id: string;
  message: string;
  delivery: "send" | "queue" | "interrupt";
  target_response_id: number | null;
  deep_research: boolean;
  llm_override: LLMOverride | null;
  mentions: Mention[];
}

export interface ChatHistoryPage {
  messageTree: Map<number, Message>;
  hasOlderMessages: boolean;
}

export interface ChatSessionStatus {
  is_processing: boolean;
  current_stream: ChatStream | null;
  has_active_subagents: boolean;
  /** Pending input can start a run now; false while the queue is paused. */
  has_startable_input: boolean;
  latest_response_id: number | null;
  /** Changes when any approval request or question of the chat session
   * opens or resolves, on any branch, a reply's or a background
   * subagent's. */
  approvals_version: string;
}

export interface ChatSessionQueue {
  /** False for incognito and anonymous chats, which have no server queue. */
  enabled: boolean;
  messages: PendingChatMessage[];
  error: string | null;
  /** A pending-message request is in flight. */
  busy: boolean;
  hasActiveSubagents: boolean;
  needsResponseSelection: boolean;
  /**
   * A queued or interrupting message's turn starts as Deep Research when
   * `deepResearch` is set, with `llmOverride` as its model and the SKILL.md
   * files of its mentioned skills after its question. A `send` gives its
   * mentions to the running response.
   */
  submit: (
    composed: ComposedMessage,
    delivery: PendingChatMessage["delivery"],
    turn: PendingTurnSettings
  ) => Promise<boolean>;
  withdraw: (id: string) => Promise<PendingChatMessage | null>;
  interrupt: (id: string) => Promise<void>;
  /** Interrupts every running subagent on the selected branch. */
  stopSubagents: () => Promise<void>;
}

/** The card's answers to a question request's questions, or text that the
 * user typed in the chat instead, which answers every question of the
 * response that waits. */
export type QuestionAnswersBody =
  | { answers: ToolQuestionAnswer[] }
  | { message: string };

export interface QuestionAnswersResponse {
  question_request_id: string;
  /** The stream that continues the response, when it runs. */
  continuation: ChatStream | null;
}

export interface ApprovalDecisionResponse {
  approval_id: string;
  decision: "APPROVED" | "REJECTED";
  // "POLICY": the action policy disabled the tool, so the approval rejected it.
  decided_via: "USER" | "SESSION_GRANT" | "POLICY";
  /** The stream that continues the suspended response, when it runs. */
  continuation: ChatStream | null;
}
