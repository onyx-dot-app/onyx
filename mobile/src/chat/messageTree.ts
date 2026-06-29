// Pure message-tree helpers. The tree is a Map keyed by nodeId, rooted at a
// synthetic system node, with branching via latestChildNodeId. Ported ~verbatim
// from web's messageTree.ts; only divergence is the trimmed minimal Message.

import { FileDescriptor, Message } from "./interfaces";

export const SYSTEM_MESSAGE_ID = -3;
export const SYSTEM_NODE_ID = -3;

export type MessageTreeState = Map<number, Message>; // key is nodeId

export function getMessageByMessageId(
  messages: MessageTreeState,
  messageId: number,
): Message | undefined {
  for (const message of Array.from(messages.values())) {
    if (message.messageId === messageId) {
      return message;
    }
  }
  return undefined;
}

function updateParentInMap(
  map: Map<number, Message>,
  parentNodeId: number,
  childNodeId: number,
  makeLatest: boolean,
): void {
  const parent = map.get(parentNodeId);
  if (parent) {
    const parentChildren = parent.childrenNodeIds || [];
    const childrenSet = new Set(parentChildren);
    let updatedChildren = parentChildren;

    if (!childrenSet.has(childNodeId)) {
      updatedChildren = [...parentChildren, childNodeId];
    }

    const updatedParent = {
      ...parent,
      childrenNodeIds: updatedChildren,
      // becomes latest only if forced, the only child, or newly added
      latestChildNodeId:
        makeLatest ||
        updatedChildren.length === 1 ||
        !childrenSet.has(childNodeId)
          ? childNodeId
          : parent.latestChildNodeId,
    };
    if (makeLatest && parent.latestChildNodeId !== childNodeId) {
      updatedParent.latestChildNodeId = childNodeId;
    }

    map.set(parentNodeId, updatedParent);
  } else {
    console.warn(
      `Parent message with nodeId ${parentNodeId} not found when updating for child ${childNodeId}`,
    );
  }
}

export function upsertMessages(
  currentMessages: MessageTreeState,
  messagesToAdd: Message[],
  makeLatestChildMessage: boolean = false,
): MessageTreeState {
  const newMessages = new Map(currentMessages);
  const messagesToAddClones = messagesToAdd.map((msg) => ({ ...msg }));

  if (newMessages.size === 0 && messagesToAddClones.length > 0) {
    const firstMessage = messagesToAddClones[0];
    if (!firstMessage) {
      throw new Error("No first message found in the message tree.");
    }
    const systemNodeId =
      firstMessage.parentNodeId !== null
        ? firstMessage.parentNodeId
        : SYSTEM_NODE_ID;
    const firstNodeId = firstMessage.nodeId;

    if (!newMessages.has(systemNodeId)) {
      const dummySystemMessage: Message = {
        messageId: SYSTEM_MESSAGE_ID,
        nodeId: systemNodeId,
        message: "",
        type: "system",
        files: [],
        parentNodeId: null,
        childrenNodeIds: [firstNodeId],
        latestChildNodeId: firstNodeId,
        packets: [],
      };
      newMessages.set(dummySystemMessage.nodeId, dummySystemMessage);
    }
    if (firstMessage.parentNodeId === null) {
      firstMessage.parentNodeId = systemNodeId;
    }
  }

  messagesToAddClones.forEach((message) => {
    newMessages.set(message.nodeId, message);

    if (message.parentNodeId !== null) {
      updateParentInMap(
        newMessages,
        message.parentNodeId,
        message.nodeId,
        makeLatestChildMessage,
      );
    }
  });

  // force the batch's last message as latest, overriding the loop above
  if (makeLatestChildMessage && messagesToAddClones.length > 0) {
    const lastMessage = messagesToAddClones[messagesToAddClones.length - 1];
    if (!lastMessage) {
      console.error("No last message found in the message tree.");
      return newMessages;
    }
    if (lastMessage.parentNodeId !== null) {
      const parent = newMessages.get(lastMessage.parentNodeId);
      if (parent && parent.latestChildNodeId !== lastMessage.nodeId) {
        const updatedParent = {
          ...parent,
          latestChildNodeId: lastMessage.nodeId,
        };
        newMessages.set(parent.nodeId, updatedParent);
      }
    }
  }

  return newMessages;
}

export function setMessageAsLatest(
  currentMessages: MessageTreeState,
  nodeId: number,
): MessageTreeState {
  const message = currentMessages.get(nodeId);
  if (!message || message.parentNodeId === null) {
    return currentMessages;
  }

  const parent = currentMessages.get(message.parentNodeId);
  if (!parent || !(parent.childrenNodeIds || []).includes(nodeId)) {
    console.warn(
      `Cannot set message ${nodeId} as latest, parent ${message.parentNodeId} or child link missing.`,
    );
    return currentMessages;
  }

  if (parent.latestChildNodeId === nodeId) {
    return currentMessages;
  }

  const newMessages = new Map(currentMessages);
  const updatedParent = {
    ...parent,
    latestChildNodeId: nodeId,
  };
  newMessages.set(parent.nodeId, updatedParent);

  return newMessages;
}

export function getLatestMessageChain(messages: MessageTreeState): Message[] {
  const chain: Message[] = [];
  if (messages.size === 0) {
    return chain;
  }

  let root: Message | undefined;
  if (messages.has(SYSTEM_NODE_ID)) {
    root = messages.get(SYSTEM_NODE_ID);
  } else {
    const potentialRoots = Array.from(messages.values()).filter(
      (message) =>
        message.parentNodeId === null || !messages.has(message.parentNodeId!),
    );
    if (potentialRoots.length > 0) {
      root =
        potentialRoots.find((m) => m.type !== "system") || potentialRoots[0];
    }
  }

  if (!root) {
    console.error("Could not determine the root message.");
    return Array.from(messages.values()).sort((a, b) => a.nodeId - b.nodeId);
  }

  let currentMessage: Message | undefined = root;
  // system root isn't part of the visible chain
  if (root.nodeId !== SYSTEM_NODE_ID && root.type !== "system") {
    chain.push(root);
  }

  while (
    currentMessage?.latestChildNodeId !== null &&
    currentMessage?.latestChildNodeId !== undefined
  ) {
    const nextNodeId = currentMessage.latestChildNodeId;
    const nextMessage = messages.get(nextNodeId);
    if (nextMessage) {
      chain.push(nextMessage);
      currentMessage = nextMessage;
    } else {
      console.warn(
        `Chain broken: Message with nodeId ${nextNodeId} not found.`,
      );
      break;
    }
  }

  return chain;
}

export function getLastSuccessfulMessageId(
  messages: MessageTreeState,
  chain?: Message[],
): number | null {
  const messageChain = chain || getLatestMessageChain(messages);
  for (let i = messageChain.length - 1; i >= 0; i--) {
    const message = messageChain[i];
    if (!message) {
      console.error(`Message ${i} not found in the message chain.`);
      continue;
    }

    if (message.type !== "error" && message.messageId !== undefined) {
      return message.messageId ?? null;
    }
  }

  // chain all errors/empty → fall back to the system node
  const systemMessage = messages.get(SYSTEM_NODE_ID);
  if (systemMessage) {
    const childNodeId = systemMessage.latestChildNodeId;
    if (childNodeId !== null && childNodeId !== undefined) {
      const firstRealMessage = messages.get(childNodeId);
      if (firstRealMessage && firstRealMessage.type !== "error") {
        return firstRealMessage.messageId ?? null;
      }
    }
    // -3 (synthetic root) here is intentional; the send caller maps it to null
    // (PR3, mirroring web's useChatController) — matches web.
    return systemMessage.messageId ?? null;
  }

  return null;
}

interface BuildEmptyMessageParams {
  messageType: "user" | "assistant";
  parentNodeId: number;
  message?: string;
  files?: FileDescriptor[];
  nodeIdOffset?: number;
}

export function buildEmptyMessage(params: BuildEmptyMessageParams): Message {
  // negative temp id avoids colliding with backend messageIds
  const tempNodeId = -1 * Date.now() - (params.nodeIdOffset || 0);
  return {
    nodeId: tempNodeId,
    message: params.message || "",
    type: params.messageType,
    files: params.files || [],
    parentNodeId: params.parentNodeId,
    packets: [],
  };
}

export function buildImmediateMessages(
  parentNodeId: number,
  userInput: string,
  files: FileDescriptor[],
): {
  initialUserNode: Message;
  initialAgentNode: Message;
} {
  // always a new nodeId so editing forks a sibling branch
  const initialUserNode = buildEmptyMessage({
    messageType: "user",
    parentNodeId,
    message: userInput,
    files,
  });
  const initialAgentNode = buildEmptyMessage({
    messageType: "assistant",
    parentNodeId: initialUserNode.nodeId,
    nodeIdOffset: 1,
  });

  initialUserNode.childrenNodeIds = [initialAgentNode.nodeId];
  initialUserNode.latestChildNodeId = initialAgentNode.nodeId;

  return {
    initialUserNode,
    initialAgentNode,
  };
}
