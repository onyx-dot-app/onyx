// Builds the message tree from a loaded session. Ported from web's
// processRawChatHistory; minimal Message (no rich types). `packets` align to
// assistant messages by ordinal — one list per assistant turn, in order.

import { BackendMessage, Message, MessageType } from "./interfaces";
import { MessageTreeState } from "./messageTree";
import { Packet } from "./streamingModels";

export function processRawChatHistory(
  rawMessages: BackendMessage[],
  packets: Packet[][],
): MessageTreeState {
  const messages: MessageTreeState = new Map();
  const parentMessageChildrenMap: Map<number, number[]> = new Map();

  let agentMessageInd = 0;

  rawMessages.forEach((messageInfo) => {
    const packetsForMessage = packets[agentMessageInd];
    if (messageInfo.message_type === "assistant") {
      agentMessageInd++;
    }

    const message: Message = {
      // loaded messages reuse message_id as nodeId (only uniqueness matters)
      nodeId: messageInfo.message_id,
      messageId: messageInfo.message_id,
      message: messageInfo.message,
      type: messageInfo.error
        ? "error"
        : (messageInfo.message_type as MessageType),
      files: messageInfo.files,
      parentNodeId: messageInfo.parent_message,
      childrenNodeIds: [],
      latestChildNodeId: messageInfo.latest_child_message,
      packets: packetsForMessage || [],
    };

    messages.set(messageInfo.message_id, message);

    if (messageInfo.parent_message !== null) {
      if (!parentMessageChildrenMap.has(messageInfo.parent_message)) {
        parentMessageChildrenMap.set(messageInfo.parent_message, []);
      }
      parentMessageChildrenMap
        .get(messageInfo.parent_message)!
        .push(messageInfo.message_id);
    }
  });

  parentMessageChildrenMap.forEach((childrenIds, parentId) => {
    childrenIds.sort((a, b) => a - b);
    const parentMessage = messages.get(parentId);
    if (parentMessage) {
      parentMessage.childrenNodeIds = childrenIds;
    }
  });

  return messages;
}
