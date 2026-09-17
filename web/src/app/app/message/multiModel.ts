import { Message } from "@/app/app/interfaces";
import { MultiModelResponse } from "@/app/app/message/interfaces";

// The model that produced a message. Error responses carry the model that
// failed, so they count for attribution too.
export function messageModelName(msg: Message): string | null {
  if (msg.type !== "assistant" && msg.type !== "error") return null;
  return msg.overridden_model || msg.modelDisplayName || null;
}

// Model-tagged children (2+) of a multi-model turn, in layout order. The
// model metadata distinguishes a real multi-model turn from a plain
// regeneration. Null when the message isn't a multi-model turn.
export function getMultiModelChildren(
  userMessage: Message,
  messageTree: Map<number, Message>
): Message[] | null {
  const childIds = userMessage.childrenNodeIds ?? [];
  if (childIds.length < 2) return null;

  const multiModelChildren = childIds
    .map((id) => messageTree.get(id))
    .filter(
      (msg): msg is Message =>
        msg !== undefined &&
        (msg.type === "assistant" || msg.type === "error") &&
        Boolean(msg.modelDisplayName || msg.overridden_model)
    );
  return multiModelChildren.length >= 2 ? multiModelChildren : null;
}

// Group a user message's sibling responses into multi-model panels.
// `modelProviderLookup` maps model → provider slug for icons and may be
// empty (e.g. the shared view). `getModelIcon` then falls back to the name.
export function getMultiModelResponses(
  userMessage: Message,
  messageTree: Map<number, Message>,
  modelProviderLookup: Map<string, string>
): MultiModelResponse[] | null {
  const multiModelChildren = getMultiModelChildren(userMessage, messageTree);
  if (!multiModelChildren) return null;

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

export interface UnresolvedMultiModelTurn {
  userMessage: Message;
  responses: Message[];
}

// The multi-model turn a new message would continue from, when the user
// never picked a preferred response. `chain` is the tree's latest chain.
export function getUnresolvedMultiModelTurn(
  chain: Message[],
  messageTree: Map<number, Message>
): UnresolvedMultiModelTurn | null {
  const lastUserMsg = [...chain].reverse().find((m) => m.type === "user");
  if (!lastUserMsg || lastUserMsg.preferredResponseId != null) return null;
  const responses = getMultiModelChildren(lastUserMsg, messageTree);
  return responses ? { userMessage: lastUserMsg, responses } : null;
}

// The model of the most recent preferred response before `excludeNodeId`'s
// turn, or null when no earlier turn has a preference.
function findPriorPreferredModel(
  chain: Message[],
  messageTree: Map<number, Message>,
  excludeNodeId: number
): string | null {
  const priorUserMsg = [...chain]
    .reverse()
    .find(
      (m) =>
        m.type === "user" &&
        m.nodeId !== excludeNodeId &&
        m.preferredResponseId != null
    );
  if (!priorUserMsg) return null;
  const priorPreferred = (priorUserMsg.childrenNodeIds ?? [])
    .map((id) => messageTree.get(id))
    .find((child) => child?.messageId === priorUserMsg.preferredResponseId);
  return (
    priorPreferred?.overridden_model || priorPreferred?.modelDisplayName || null
  );
}

// The response in view per turn (user message nodeId), written by the panel
// view's narrow-screen carousel and read at send time. An entry exists only
// while the carousel shows one response at a time.
const mostVisibleResponseByTurn = new Map<number, number>();

export function setMostVisibleResponseId(
  userNodeId: number,
  responseMessageId: number | null
): void {
  if (responseMessageId == null) {
    mostVisibleResponseByTurn.delete(userNodeId);
  } else {
    mostVisibleResponseByTurn.set(userNodeId, responseMessageId);
  }
}

export function getMostVisibleResponseId(userNodeId: number): number | null {
  return mostVisibleResponseByTurn.get(userNodeId) ?? null;
}

// The response a send assumes as preferred: the response in view on narrow
// screens, else the prior turn's preferred model when it answered this turn
// too, else the first model (right-most, last child). Errors never assumed.
export function chooseImplicitPreferred(
  chain: Message[],
  messageTree: Map<number, Message>,
  turn: UnresolvedMultiModelTurn,
  visibleResponseId: number | null = null
): Message | null {
  const candidates = turn.responses.filter(
    (r) => r.type === "assistant" && r.messageId != null
  );
  if (visibleResponseId != null) {
    const visible = candidates.find((r) => r.messageId === visibleResponseId);
    if (visible) return visible;
  }
  const priorModel = findPriorPreferredModel(
    chain,
    messageTree,
    turn.userMessage.nodeId
  );
  const match = priorModel
    ? candidates.find(
        (r) => (r.overridden_model || r.modelDisplayName) === priorModel
      )
    : undefined;
  return match ?? candidates.at(-1) ?? null;
}

// preferredResponseId and latestChildNodeId move together, as in the backend's
// set_preferred_response. A disagreeing local chain walk breaks the next send.
// Null clears the preference and leaves the chain tip alone.
export function applyPreferredResponse(
  tree: Map<number, Message>,
  userNodeId: number,
  response: Pick<Message, "messageId" | "nodeId"> | null
): Map<number, Message> | null {
  const userMsg = tree.get(userNodeId);
  if (!userMsg) return null;
  const updated = new Map(tree);
  updated.set(
    userNodeId,
    response
      ? {
          ...userMsg,
          preferredResponseId: response.messageId,
          latestChildNodeId: response.nodeId,
        }
      : { ...userMsg, preferredResponseId: undefined }
  );
  return updated;
}
