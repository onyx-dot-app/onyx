/**
 * Agent Client Protocol (ACP) types the timeline reads.
 *
 * A subset of the ACP schema, matching the `agent-client-protocol` package
 * the backend uses (v0.7.1, `backend/onyx/server/features/build/sandbox/event_schema.py`).
 * Field names are the JSON wire names. Add types here as a producer starts
 * sending them; do not rename fields.
 */

/** Onyx data that ACP has no field for. Carried in `_meta.onyx`. */
export interface OnyxMeta {
  /**
   * The tool call was stopped before it finished. ACP's tool status has no
   * cancelled state, so this is kept apart from `failed`.
   */
  cancelled?: boolean;
  /**
   * Identity of a message or thought part. Chunks with the same part id
   * update one entry, so a replayed or reconnected stream does not repeat
   * text.
   */
  partId?: string;
  /** The part's full current text. Replaces the text received so far. */
  snapshotText?: string;
  /** For a plan entry: its present-tense label while it runs. */
  activeForm?: string;
}

/** ACP's extension field on every object. */
export interface AcpMeta {
  onyx?: OnyxMeta;
  [key: string]: unknown;
}

export interface AcpTextContentBlock {
  type: "text";
  text: string;
  _meta?: AcpMeta;
}

export interface AcpImageContentBlock {
  type: "image";
  data: string;
  mimeType: string;
  uri?: string | null;
  _meta?: AcpMeta;
}

export interface AcpAudioContentBlock {
  type: "audio";
  data: string;
  mimeType: string;
  _meta?: AcpMeta;
}

export interface AcpResourceLinkContentBlock {
  type: "resource_link";
  uri: string;
  name: string;
  title?: string | null;
  description?: string | null;
  mimeType?: string | null;
  size?: number | null;
  _meta?: AcpMeta;
}

export type AcpResourceContents =
  | { uri: string; text: string; mimeType?: string | null; _meta?: AcpMeta }
  | { uri: string; blob: string; mimeType?: string | null; _meta?: AcpMeta };

export interface AcpEmbeddedResourceContentBlock {
  type: "resource";
  resource: AcpResourceContents;
  _meta?: AcpMeta;
}

export type AcpContentBlock =
  | AcpTextContentBlock
  | AcpImageContentBlock
  | AcpAudioContentBlock
  | AcpResourceLinkContentBlock
  | AcpEmbeddedResourceContentBlock;

export type AcpToolKind =
  | "read"
  | "edit"
  | "delete"
  | "move"
  | "search"
  | "execute"
  | "think"
  | "fetch"
  | "switch_mode"
  | "other";

export type AcpToolCallStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "failed";

export type AcpToolCallContent =
  | { type: "content"; content: AcpContentBlock; _meta?: AcpMeta }
  | {
      type: "diff";
      path: string;
      oldText?: string | null;
      newText: string;
      _meta?: AcpMeta;
    }
  | { type: "terminal"; terminalId: string; _meta?: AcpMeta };

export interface AcpToolCallLocation {
  path: string;
  line?: number | null;
  _meta?: AcpMeta;
}

/** The fields a tool call start and a tool call update share. */
interface AcpToolCallFields {
  toolCallId: string;
  kind?: AcpToolKind | null;
  status?: AcpToolCallStatus | null;
  content?: AcpToolCallContent[] | null;
  locations?: AcpToolCallLocation[] | null;
  rawInput?: unknown;
  rawOutput?: unknown;
  _meta?: AcpMeta;
}

export interface AcpToolCallStart extends AcpToolCallFields {
  sessionUpdate: "tool_call";
  title: string;
}

/** Changes to an earlier tool call. Fields left out keep their value. */
export interface AcpToolCallProgress extends AcpToolCallFields {
  sessionUpdate: "tool_call_update";
  title?: string | null;
}

export interface AcpAgentMessageChunk {
  sessionUpdate: "agent_message_chunk";
  content: AcpContentBlock;
  _meta?: AcpMeta;
}

export interface AcpAgentThoughtChunk {
  sessionUpdate: "agent_thought_chunk";
  content: AcpContentBlock;
  _meta?: AcpMeta;
}

export interface AcpPlanEntry {
  content: string;
  priority: "high" | "medium" | "low";
  status: "pending" | "in_progress" | "completed";
  _meta?: AcpMeta;
}

/** The whole current plan. Each update replaces the previous one. */
export interface AcpAgentPlanUpdate {
  sessionUpdate: "plan";
  entries: AcpPlanEntry[];
  _meta?: AcpMeta;
}

export type AcpSessionUpdate =
  | AcpAgentMessageChunk
  | AcpAgentThoughtChunk
  | AcpToolCallStart
  | AcpToolCallProgress
  | AcpAgentPlanUpdate;

export type AcpStopReason =
  | "end_turn"
  | "max_tokens"
  | "max_turn_requests"
  | "refusal"
  | "cancelled";
