import type { Message } from "@/app/app/types";
import type { LLMOverride } from "@/app/app/services/lib";
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

/** A picked skill at the version the user ran when its question was
 * accepted. */
export interface RecordedSkillMention extends SkillMention {
  version_id: string;
}

/** A mention as its question's turn resolved it. Mirrors `RecordedMention`
 * in `backend/onyx/chat/mention_models.py`. */
export type RecordedMention = RecordedSkillMention;

/** A question as the user wrote it: its text and what the user tagged in it.
 * Mentions come only from the `@` menu; the text holds an `@name` for each,
 * and plain `@name` text mentions nothing. */
export interface ComposedMessage {
  message: string;
  mentions: Mention[];
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
  current_stream: { stream_id: number } | null;
  has_active_subagents: boolean;
  /** Pending input can start a run now; false while the queue is paused. */
  has_startable_input: boolean;
  latest_response_id: number | null;
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
   * files of its mentioned skills before its question. A `send` into a
   * running response applies no mentions.
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
