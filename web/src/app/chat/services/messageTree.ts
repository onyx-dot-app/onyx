import { FileDescriptor, Message } from "../interfaces";

export const SYSTEM_MESSAGE_ID = -3;
export const SYSTEM_NODE_ID = -3;

export type MessageTreeState = Map<number, Message>; // key is nodeId

export function createInitialMessageTreeState(
  initialMessages?: Map<number, Message> | Message[]
): MessageTreeState {
  if (!initialMessages) {
    return new Map();
  }
  if (initialMessages instanceof Map) {
    return new Map(initialMessages); // Shallow copy
  }
  return new Map(initialMessages.map((msg) => [msg.nodeId, msg]));
}

export function getMessage(
  messages: MessageTreeState,
  nodeId: number
): Message | undefined {
  return messages.get(nodeId);
}

export function getMessageByMessageId(
  messages: MessageTreeState,
  messageId: number
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
  makeLatest: boolean
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
      // Update latestChild only if explicitly requested or if it's the only child,
      // or if the child was newly added
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
      `Parent message with nodeId ${parentNodeId} not found when updating for child ${childNodeId}`
    );
  }
}

export function upsertMessages(
  currentMessages: MessageTreeState,
  messagesToAdd: Message[],
  makeLatestChildMessage: boolean = false
): MessageTreeState {
  let newMessages = new Map(currentMessages);
  let messagesToAddClones = messagesToAdd.map((msg) => ({ ...msg })); // Clone all incoming messages

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

    // Check if system message needs to be added or already exists (e.g., from parentNodeId)
    if (!newMessages.has(systemNodeId)) {
      const dummySystemMessage: Message = {
        messageId: SYSTEM_MESSAGE_ID,
        nodeId: systemNodeId,
        message: "",
        type: "system",
        files: [],
        toolCall: null,
        parentNodeId: null,
        childrenNodeIds: [firstNodeId],
        latestChildNodeId: firstNodeId,
        packets: [],
      };
      newMessages.set(dummySystemMessage.nodeId, dummySystemMessage);
    }
    // Ensure the first message points to the system message if its parent was null
    if (!firstMessage) {
      console.error("No first message found in the message tree.");
      return newMessages;
    }
    if (firstMessage.parentNodeId === null) {
      firstMessage.parentNodeId = systemNodeId;
    }
  }

  messagesToAddClones.forEach((message) => {
    // Add/update the message itself
    newMessages.set(message.nodeId, message);

    // Update parent's children if the message has a parent
    if (message.parentNodeId !== null) {
      // When adding multiple messages, only make the *first* one added potentially the latest,
      // unless `makeLatestChildMessage` is true for all.
      // Let's stick to the original logic: update parent, potentially making this message latest
      // based on makeLatestChildMessage flag OR if it's a new child being added.
      updateParentInMap(
        newMessages,
        message.parentNodeId,
        message.nodeId,
        makeLatestChildMessage
      );
    }
  });

  // Explicitly set the last message of the batch as the latest if requested,
  // overriding previous updates within the loop if necessary.
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

export function removeMessage(
  currentMessages: MessageTreeState,
  nodeIdToRemove: number
): MessageTreeState {
  if (!currentMessages.has(nodeIdToRemove)) {
    return currentMessages; // Return original if message doesn't exist
  }

  const newMessages = new Map(currentMessages);
  const messageToRemove = newMessages.get(nodeIdToRemove)!;

  // Collect all descendant IDs to remove
  const idsToRemove = new Set<number>();
  const queue: number[] = [nodeIdToRemove];

  while (queue.length > 0) {
    const currentId = queue.shift()!;
    if (!newMessages.has(currentId) || idsToRemove.has(currentId)) continue;
    idsToRemove.add(currentId);

    const currentMsg = newMessages.get(currentId);
    if (currentMsg?.childrenNodeIds) {
      currentMsg.childrenNodeIds.forEach((childId) => queue.push(childId));
    }
  }

  // Remove all descendants
  idsToRemove.forEach((id) => newMessages.delete(id));

  // Update the parent
  if (messageToRemove.parentNodeId !== null) {
    const parent = newMessages.get(messageToRemove.parentNodeId);
    if (parent) {
      const updatedChildren = (parent.childrenNodeIds || []).filter(
        (id) => id !== nodeIdToRemove
      );
      const updatedParent = {
        ...parent,
        childrenNodeIds: updatedChildren,
        // If the removed message was the latest, find the new latest (last in the updated children list)
        latestChildNodeId:
          parent.latestChildNodeId === nodeIdToRemove
            ? updatedChildren.length > 0
              ? updatedChildren[updatedChildren.length - 1]
              : null
            : parent.latestChildNodeId,
      };
      newMessages.set(parent.nodeId, updatedParent);
    }
  }

  return newMessages;
}

export function setMessageAsLatest(
  currentMessages: MessageTreeState,
  nodeId: number
): MessageTreeState {
  const message = currentMessages.get(nodeId);
  if (!message || message.parentNodeId === null) {
    return currentMessages; // Cannot set root or non-existent message as latest
  }

  const parent = currentMessages.get(message.parentNodeId);
  if (!parent || !(parent.childrenNodeIds || []).includes(nodeId)) {
    console.warn(
      `Cannot set message ${nodeId} as latest, parent ${message.parentNodeId} or child link missing.`
    );
    return currentMessages; // Parent doesn't exist or doesn't list this message as a child
  }

  if (parent.latestChildNodeId === nodeId) {
    return currentMessages; // Already the latest
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

  // Find the root message
  let root: Message | undefined;
  if (messages.has(SYSTEM_NODE_ID)) {
    root = messages.get(SYSTEM_NODE_ID);
  } else {
    // Use Array.from to fix linter error
    const potentialRoots = Array.from(messages.values()).filter(
      (message) =>
        message.parentNodeId === null || !messages.has(message.parentNodeId!)
    );
    if (potentialRoots.length > 0) {
      // Prefer non-system message if multiple roots found somehow
      root =
        potentialRoots.find((m) => m.type !== "system") || potentialRoots[0];
    }
  }

  if (!root) {
    console.error("Could not determine the root message.");
    // Fallback: return flat list sorted by nodeId perhaps? Or empty?
    return Array.from(messages.values()).sort((a, b) => a.nodeId - b.nodeId);
  }

  let currentMessage: Message | undefined = root;
  // The root itself (like SYSTEM_MESSAGE) might not be part of the visible chain
  if (root.nodeId !== SYSTEM_NODE_ID && root.type !== "system") {
    // Need to clone message for safety? If MessageTreeState guarantees immutability maybe not.
    // Let's assume Message objects within the map are treated as immutable.
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
        `Chain broken: Message with nodeId ${nextNodeId} not found.`
      );
      break;
    }
  }

  return chain;
}

export function getHumanAndAIMessageFromMessageNumber(
  messages: MessageTreeState,
  messageNumber: number
): { humanMessage: Message | null; aiMessage: Message | null } {
  const latestChain = getLatestMessageChain(messages);
  const messageIndex = latestChain.findIndex(
    (msg) => msg.messageId === messageNumber
  );

  if (messageIndex === -1) {
    // Maybe the message exists but isn't in the latest chain? Search the whole map.
    const message = getMessageByMessageId(messages, messageNumber);
    if (!message) return { humanMessage: null, aiMessage: null };

    if (message.type === "user") {
      // Find its latest child that is an assistant
      const potentialAiMessage =
        message.latestChildNodeId !== null &&
        message.latestChildNodeId !== undefined
          ? messages.get(message.latestChildNodeId)
          : undefined;
      const aiMessage =
        potentialAiMessage?.type === "assistant" ? potentialAiMessage : null;
      return { humanMessage: message, aiMessage };
    } else if (message.type === "assistant" || message.type === "error") {
      const humanMessage =
        message.parentNodeId !== null
          ? messages.get(message.parentNodeId)
          : null;
      return {
        humanMessage: humanMessage?.type === "user" ? humanMessage : null,
        aiMessage: message,
      };
    }
    return { humanMessage: null, aiMessage: null };
  }

  // Message is in the latest chain
  const message = latestChain[messageIndex];
  if (!message) {
    console.error(`Message ${messageNumber} not found in the latest chain.`);
    return { humanMessage: null, aiMessage: null };
  }

  if (message.type === "user") {
    const potentialAiMessage = latestChain[messageIndex + 1];
    const aiMessage =
      potentialAiMessage?.type === "assistant" &&
      potentialAiMessage.parentNodeId === message.nodeId
        ? potentialAiMessage
        : null;
    return { humanMessage: message, aiMessage };
  } else if (message.type === "assistant" || message.type === "error") {
    const potentialHumanMessage = latestChain[messageIndex - 1];
    const humanMessage =
      potentialHumanMessage?.type === "user" &&
      message.parentNodeId === potentialHumanMessage.nodeId
        ? potentialHumanMessage
        : null;
    return { humanMessage, aiMessage: message };
  }

  return { humanMessage: null, aiMessage: null };
}

export function getLastSuccessfulMessageId(
  messages: MessageTreeState,
  chain?: Message[]
): number | null {
  const messageChain = chain || getLatestMessageChain(messages);
  for (let i = messageChain.length - 1; i >= 0; i--) {
    const message = messageChain[i];
    if (!message) {
      console.error(`Message ${i} not found in the message chain.`);
      continue;
    }

    // don't include failed / not-completed messages
    if (message.type !== "error" && message.messageId !== undefined) {
      return message.messageId ?? null;
    }
  }

  // If the chain starts with an error or is empty, check for system message
  const systemMessage = messages.get(SYSTEM_NODE_ID);
  if (systemMessage) {
    // Check if the system message itself is considered "successful" (it usually is)
    // Or if it has a successful child
    const childNodeId = systemMessage.latestChildNodeId;
    if (childNodeId !== null && childNodeId !== undefined) {
      const firstRealMessage = messages.get(childNodeId);
      if (firstRealMessage && firstRealMessage.type !== "error") {
        return firstRealMessage.messageId ?? null;
      }
    }
    // If no successful child, return the system message ID itself as the root?
    // This matches the class behavior implicitly returning the root ID if nothing else works.
    return systemMessage.messageId ?? null;
  }

  return null; // No successful message found
}

interface BuildEmptyMessageParams {
  messageType: "user" | "assistant";
  parentNodeId: number;
  message?: string;
  files?: FileDescriptor[];
  nodeIdOffset?: number;
}

export const buildEmptyMessage = (params: BuildEmptyMessageParams): Message => {
  // use negative number to avoid conflicts with messageIds
  const tempNodeId = -1 * Date.now() - (params.nodeIdOffset || 0);
  return {
    nodeId: tempNodeId,
    message: params.message || "",
    type: params.messageType,
    files: params.files || [],
    toolCall: null,
    parentNodeId: params.parentNodeId,
    packets: [],
  };
};

export const buildImmediateMessages = (
  parentNodeId: number,
  userInput: string,
  files: FileDescriptor[],
  messageToResend?: Message
): {
  initialUserNode: Message;
  initialAssistantNode: Message;
} => {
  const initialUserNode = messageToResend
    ? { ...messageToResend } // clone the message to avoid mutating the original
    : buildEmptyMessage({
        messageType: "user",
        parentNodeId,
        message: userInput,
        files,
      });
  const initialAssistantNode = buildEmptyMessage({
    messageType: "assistant",
    parentNodeId: initialUserNode.nodeId,
    nodeIdOffset: 1,
  });

  initialUserNode.childrenNodeIds = initialUserNode.childrenNodeIds
    ? [...initialUserNode.childrenNodeIds, initialAssistantNode.nodeId]
    : [initialAssistantNode.nodeId];
  initialUserNode.latestChildNodeId = initialAssistantNode.nodeId;

  return {
    initialUserNode,
    initialAssistantNode,
  };
};
