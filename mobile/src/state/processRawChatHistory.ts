// Build the in-memory message tree from a backend chat session's flat message list.
// Ported from web `processRawChatHistory` (web/src/app/app/services/lib.tsx) —
// keyed by nodeId = message_id, with parent/child links rebuilt from parent_message.
//
// Mobile divergence: `toolCall` is set to null here (the mobile Message.toolCall is
// ToolCallMetadata while the backend sends a ToolCallFinalResult, and the mobile
// thread does not render historical tool calls yet). All other rendered fields
// (text, type, files, tree links, packets, citations/docs) are carried faithfully.

import {
  RetrievalType,
  type BackendMessage,
  type CitationMap,
  type FeedbackType,
  type Message,
  type Packet,
  type ResearchType,
} from "@/lib/types";
import type { MessageTreeState } from "./messageTree";

export function processRawChatHistory(
  rawMessages: BackendMessage[],
  packets: Packet[][],
): MessageTreeState {
  const messages: MessageTreeState = new Map();
  const parentChildren = new Map<number, number[]>();

  let agentMessageInd = 0;

  rawMessages.forEach((info) => {
    const packetsForMessage = packets[agentMessageInd];
    if (info.message_type === "assistant") {
      agentMessageInd++;
    }

    const hasContextDocs = (info.context_docs || []).length > 0;
    const retrievalType = hasContextDocs
      ? info.rephrased_query
        ? RetrievalType.Search
        : RetrievalType.SelectedDocs
      : RetrievalType.None;

    const message: Message = {
      nodeId: info.message_id,
      messageId: info.message_id,
      message: info.message,
      type: info.error
        ? "error"
        : (info.message_type as "user" | "assistant"),
      files: info.files ?? [],
      alternateAgentID:
        info.alternate_assistant_id !== null
          ? Number(info.alternate_assistant_id)
          : null,
      ...(info.message_type === "assistant"
        ? {
            retrievalType,
            researchType: (info.research_type as ResearchType) ?? undefined,
            query: info.rephrased_query,
            documents: info.context_docs || [],
            citations: (info.citations as CitationMap) || {},
            processingDurationSeconds: info.processing_duration_seconds,
          }
        : {}),
      toolCall: null,
      parentNodeId: info.parent_message,
      childrenNodeIds: [],
      latestChildNodeId: info.latest_child_message,
      overridden_model: info.overridden_model,
      packets: packetsForMessage || [],
      currentFeedback: info.current_feedback as FeedbackType | null,
      preferredResponseId: info.preferred_response_id ?? null,
      modelDisplayName: info.model_display_name ?? null,
    };

    messages.set(info.message_id, message);

    if (info.parent_message !== null) {
      const siblings = parentChildren.get(info.parent_message) ?? [];
      siblings.push(info.message_id);
      parentChildren.set(info.parent_message, siblings);
    }
  });

  // Populate childrenNodeIds (sorted) on each parent.
  parentChildren.forEach((childrenIds, parentId) => {
    childrenIds.sort((a, b) => a - b);
    const parent = messages.get(parentId);
    if (parent) {
      parent.childrenNodeIds = childrenIds;
    }
  });

  return messages;
}
