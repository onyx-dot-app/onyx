import { Message } from "@/app/app/interfaces";
import { MultiModelResponse } from "@/app/app/message/interfaces";

/**
 * Group a user message's sibling assistant responses into multi-model panels.
 *
 * A multi-model turn is a user message with 2+ assistant/error children that
 * each carry a model name (`modelDisplayName` or `overridden_model`). That
 * metadata is what distinguishes a real multi-model turn from a plain
 * regeneration, which also produces sibling assistant messages. Returns null
 * when the message isn't a multi-model turn.
 *
 * `modelProviderLookup` maps a model identifier → provider slug for icon
 * resolution. Pass an empty map when the provider list is unavailable (e.g. the
 * read-only shared view). `getModelIcon` then falls back to the model name.
 */
export function getMultiModelResponses(
  userMessage: Message,
  messageTree: Map<number, Message>,
  modelProviderLookup: Map<string, string>
): MultiModelResponse[] | null {
  const childIds = userMessage.childrenNodeIds ?? [];
  if (childIds.length < 2) return null;

  const assistantChildren = childIds
    .map((id) => messageTree.get(id))
    .filter(
      (msg): msg is Message =>
        msg !== undefined && (msg.type === "assistant" || msg.type === "error")
    );

  const multiModelChildren = assistantChildren.filter(
    (msg) => msg.modelDisplayName || msg.overridden_model
  );
  if (multiModelChildren.length < 2) return null;

  return multiModelChildren.map((msg, idx): MultiModelResponse => {
    const modelVersion =
      msg.overridden_model || msg.modelDisplayName || "Model";
    const provider = modelProviderLookup.get(modelVersion) ?? "";
    const displayName = msg.modelDisplayName || modelVersion;
    const isError = msg.type === "error";
    return {
      modelIndex: idx,
      provider,
      modelName: modelVersion,
      displayName,
      packets: msg.packets || [],
      packetCount: msg.packetCount || msg.packets?.length || 0,
      nodeId: msg.nodeId,
      messageId: msg.messageId,
      currentFeedback: msg.currentFeedback,
      isGenerating: msg.is_generating || false,
      errorMessage: isError ? msg.message : null,
      errorCode: isError ? msg.errorCode : null,
      isRetryable: isError ? msg.isRetryable : undefined,
      errorStackTrace: isError ? msg.stackTrace : null,
      errorDetails: isError ? msg.errorDetails : null,
    };
  });
}
