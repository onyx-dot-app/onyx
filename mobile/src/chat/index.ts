// Barrel for the chat streaming-send layer.
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
