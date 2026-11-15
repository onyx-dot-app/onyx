import type { ChatSessionStatus, ChatStream } from "../src/types/api-types";

export const chatStream = (
  streamId: number,
  responseIds: number[] = []
): ChatStream => ({ stream_id: streamId, response_ids: responseIds });

/** A status read of an idle session, with `fields` on top. */
export const idle = (
  fields: Partial<ChatSessionStatus> = {}
): ChatSessionStatus => ({
  is_processing: false,
  has_active_subagents: false,
  has_startable_input: false,
  latest_response_id: null,
  current_stream: null,
  approvals_version: null,
  ...fields,
});

/** A status read of a session that runs `stream`. */
export const runs = (stream: ChatStream): ChatSessionStatus => ({
  ...idle(),
  is_processing: true,
  current_stream: stream,
});

/** What a status read that reports stream `streamId` ends a wait with. */
export const offer = (
  attachable: (stream: ChatStream) => boolean,
  streamId: number
): ChatSessionStatus =>
  attachable(chatStream(streamId)) ? runs(chatStream(streamId)) : idle();
