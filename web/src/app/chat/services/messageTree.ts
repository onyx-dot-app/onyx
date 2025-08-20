import { Message } from "../interfaces";

export const SYSTEM_MESSAGE_ID = -3;

export type MessageTreeState = Map<number, Message>;

export function createInitialMessageTreeState(
  initialMessages?: Map<number, Message> | Message[]
): MessageTreeState {
  if (!initialMessages) {
    return new Map();
  }
  if (initialMessages instanceof Map) {
    return new Map(initialMessages); // Shallow copy
  }
  return new Map(initialMessages.map((msg) => [msg.messageId, msg]));
}

export function getMessage(
  messages: MessageTreeState,
  messageId: number
): Message | undefined {
  return messages.get(messageId);
}

function updateParentInMap(
  map: Map<number, Message>,
  parentId: number,
  childId: number,
  makeLatest: boolean
): void {
  const parent = map.get(parentId);
  if (parent) {
    const parentChildren = parent.childrenMessageIds || [];
    const childrenSet = new Set(parentChildren);
    let updatedChildren = parentChildren;

    if (!childrenSet.has(childId)) {
      updatedChildren = [...parentChildren, childId];
    }

    const updatedParent = {
      ...parent,
      childrenMessageIds: updatedChildren,
      // Update latestChild only if explicitly requested or if it's the only child,
      // or if the child was newly added
      latestChildMessageId:
        makeLatest || updatedChildren.length === 1 || !childrenSet.has(childId)
          ? childId
          : parent.latestChildMessageId,
    };
    if (makeLatest && parent.latestChildMessageId !== childId) {
      updatedParent.latestChildMessageId = childId;
    }

    map.set(parentId, updatedParent);
  } else {
    console.warn(
      `Parent message with ID ${parentId} not found when updating for child ${childId}`
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
    const systemMessageId =
      firstMessage.parentMessageId !== null
        ? firstMessage.parentMessageId
        : SYSTEM_MESSAGE_ID;
    const firstMessageId = firstMessage.messageId;

    // Check if system message needs to be added or already exists (e.g., from parentMessageId)
    if (!newMessages.has(systemMessageId)) {
      const dummySystemMessage: Message = {
        messageId: systemMessageId,
        message: "",
        type: "system",
        files: [],
        toolCall: null,
        parentMessageId: null,
        childrenMessageIds: [firstMessageId],
        latestChildMessageId: firstMessageId,
        packets: [],
      };
      newMessages.set(dummySystemMessage.messageId, dummySystemMessage);
    }
    // Ensure the first message points to the system message if its parent was null
    if (!firstMessage) {
      console.error("No first message found in the message tree.");
      return newMessages;
    }
    if (firstMessage.parentMessageId === null) {
      firstMessage.parentMessageId = systemMessageId;
    }
  }

  messagesToAddClones.forEach((message) => {
    // Add/update the message itself
    newMessages.set(message.messageId, message);

    // Update parent's children if the message has a parent
    if (message.parentMessageId !== null) {
      // When adding multiple messages, only make the *first* one added potentially the latest,
      // unless `makeLatestChildMessage` is true for all.
      // Let's stick to the original logic: update parent, potentially making this message latest
      // based on makeLatestChildMessage flag OR if it's a new child being added.
      updateParentInMap(
        newMessages,
        message.parentMessageId,
        message.messageId,
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
    if (lastMessage.parentMessageId !== null) {
      const parent = newMessages.get(lastMessage.parentMessageId);
      if (parent && parent.latestChildMessageId !== lastMessage.messageId) {
        const updatedParent = {
          ...parent,
          latestChildMessageId: lastMessage.messageId,
        };
        newMessages.set(parent.messageId, updatedParent);
      }
    }
  }

  return newMessages;
}

export function removeMessage(
  currentMessages: MessageTreeState,
  messageIdToRemove: number
): MessageTreeState {
  if (!currentMessages.has(messageIdToRemove)) {
    return currentMessages; // Return original if message doesn't exist
  }

  const newMessages = new Map(currentMessages);
  const messageToRemove = newMessages.get(messageIdToRemove)!;

  // Collect all descendant IDs to remove
  const idsToRemove = new Set<number>();
  const queue: number[] = [messageIdToRemove];

  while (queue.length > 0) {
    const currentId = queue.shift()!;
    if (!newMessages.has(currentId) || idsToRemove.has(currentId)) continue;
    idsToRemove.add(currentId);

    const currentMsg = newMessages.get(currentId);
    if (currentMsg?.childrenMessageIds) {
      currentMsg.childrenMessageIds.forEach((childId) => queue.push(childId));
    }
  }

  // Remove all descendants
  idsToRemove.forEach((id) => newMessages.delete(id));

  // Update the parent
  if (messageToRemove.parentMessageId !== null) {
    const parent = newMessages.get(messageToRemove.parentMessageId);
    if (parent) {
      const updatedChildren = (parent.childrenMessageIds || []).filter(
        (id) => id !== messageIdToRemove
      );
      const updatedParent = {
        ...parent,
        childrenMessageIds: updatedChildren,
        // If the removed message was the latest, find the new latest (last in the updated children list)
        latestChildMessageId:
          parent.latestChildMessageId === messageIdToRemove
            ? updatedChildren.length > 0
              ? updatedChildren[updatedChildren.length - 1]
              : null
            : parent.latestChildMessageId,
      };
      newMessages.set(parent.messageId, updatedParent);
    }
  }

  return newMessages;
}

export function setMessageAsLatest(
  currentMessages: MessageTreeState,
  messageId: number
): MessageTreeState {
  const message = currentMessages.get(messageId);
  if (!message || message.parentMessageId === null) {
    return currentMessages; // Cannot set root or non-existent message as latest
  }

  const parent = currentMessages.get(message.parentMessageId);
  if (!parent || !(parent.childrenMessageIds || []).includes(messageId)) {
    console.warn(
      `Cannot set message ${messageId} as latest, parent ${message.parentMessageId} or child link missing.`
    );
    return currentMessages; // Parent doesn't exist or doesn't list this message as a child
  }

  if (parent.latestChildMessageId === messageId) {
    return currentMessages; // Already the latest
  }

  const newMessages = new Map(currentMessages);
  const updatedParent = {
    ...parent,
    latestChildMessageId: messageId,
  };
  newMessages.set(parent.messageId, updatedParent);

  return newMessages;
}

export function getLatestMessageChain(messages: MessageTreeState): Message[] {
  const chain: Message[] = [];
  if (messages.size === 0) {
    return chain;
  }

  // Find the root message
  let root: Message | undefined;
  if (messages.has(SYSTEM_MESSAGE_ID)) {
    root = messages.get(SYSTEM_MESSAGE_ID);
  } else {
    // Use Array.from to fix linter error
    const potentialRoots = Array.from(messages.values()).filter(
      (message) =>
        message.parentMessageId === null ||
        !messages.has(message.parentMessageId!)
    );
    if (potentialRoots.length > 0) {
      // Prefer non-system message if multiple roots found somehow
      root =
        potentialRoots.find((m) => m.type !== "system") || potentialRoots[0];
    }
  }

  if (!root) {
    console.error("Could not determine the root message.");
    // Fallback: return flat list sorted by ID perhaps? Or empty?
    return Array.from(messages.values()).sort(
      (a, b) => a.messageId - b.messageId
    );
  }

  let currentMessage: Message | undefined = root;
  // The root itself (like SYSTEM_MESSAGE) might not be part of the visible chain
  if (root.messageId !== SYSTEM_MESSAGE_ID && root.type !== "system") {
    // Need to clone message for safety? If MessageTreeState guarantees immutability maybe not.
    // Let's assume Message objects within the map are treated as immutable.
    chain.push(root);
  }

  while (
    currentMessage?.latestChildMessageId !== null &&
    currentMessage?.latestChildMessageId !== undefined
  ) {
    const nextMessageId = currentMessage.latestChildMessageId;
    const nextMessage = messages.get(nextMessageId);
    if (nextMessage) {
      chain.push(nextMessage);
      currentMessage = nextMessage;
    } else {
      console.warn(`Chain broken: Message ${nextMessageId} not found.`);
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
    const message = messages.get(messageNumber);
    if (!message) return { humanMessage: null, aiMessage: null };

    if (message.type === "user") {
      // Find its latest child that is an assistant
      const potentialAiMessage =
        message.latestChildMessageId !== null &&
        message.latestChildMessageId !== undefined
          ? messages.get(message.latestChildMessageId)
          : undefined;
      const aiMessage =
        potentialAiMessage?.type === "assistant" ? potentialAiMessage : null;
      return { humanMessage: message, aiMessage };
    } else if (message.type === "assistant" || message.type === "error") {
      const humanMessage =
        message.parentMessageId !== null
          ? messages.get(message.parentMessageId)
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
      potentialAiMessage.parentMessageId === message.messageId
        ? potentialAiMessage
        : null;
    return { humanMessage: message, aiMessage };
  } else if (message.type === "assistant" || message.type === "error") {
    const potentialHumanMessage = latestChain[messageIndex - 1];
    const humanMessage =
      potentialHumanMessage?.type === "user" &&
      message.parentMessageId === potentialHumanMessage.messageId
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
    if (message.type !== "error") {
      return message.messageId;
    }
  }

  // If the chain starts with an error or is empty, check for system message
  const systemMessage = messages.get(SYSTEM_MESSAGE_ID);
  if (systemMessage) {
    // Check if the system message itself is considered "successful" (it usually is)
    // Or if it has a successful child
    const childId = systemMessage.latestChildMessageId;
    if (childId !== null && childId !== undefined) {
      const firstRealMessage = messages.get(childId);
      if (firstRealMessage && firstRealMessage.type !== "error") {
        return firstRealMessage.messageId;
      }
    }
    // If no successful child, return the system message ID itself as the root?
    // This matches the class behavior implicitly returning the root ID if nothing else works.
    return systemMessage.messageId;
  }

  return null; // No successful message found
}
