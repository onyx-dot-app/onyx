// Barrel for the chat streaming-send layer.
//
// The hook (useSendMessage) orchestrates the optimistic send against the Zustand
// store; the transport (streamChatMessage) lives in @/lib/api/sendMessage and is
// re-exported here for convenience so consumers can import everything chat-send
// from "@/chat".
export {
  useSendMessage,
  consumePendingRefetch,
  defaultStreamConfig,
  type UseSendMessageResult,
} from "./useSendMessage";

export {
  useComposerAttachments,
  type ComposerAttachment,
  type UseComposerAttachmentsResult,
} from "./useComposerAttachments";

export {
  useHydrateCurrentSession,
  type HydrateCurrentSessionResult,
} from "./useHydrateCurrentSession";

export {
  streamChatMessage,
  AUTO_PLACE_AFTER_LATEST_MESSAGE,
  type SendMessageRequest,
  type LLMOverride,
  type MessageOrigin,
} from "@/lib/api/sendMessage";
