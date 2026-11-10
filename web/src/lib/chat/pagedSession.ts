import type { BackendChatSession, Message } from "@/app/app/types";
import { processRawChatHistory } from "@/app/app/services/lib";
import { getLatestMessageChain } from "@/app/app/services/messageTree";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import type { ChatHistoryPage } from "@/lib/chat/types";

/** Messages of the current branch that one page of a chat holds. */
export const CHAT_PAGE_SIZE = 20;

/** Keep loaded history when the latest page attaches to the selected branch. */
export function mergeLatestChatPage(
  page: BackendChatSession,
  current: ChatHistoryPage
): ChatHistoryPage {
  const saved = processRawChatHistory(page.messages, page.packets);
  const local = current.messageTree;
  const first = getLatestMessageChain(saved)[0];
  const localChain = getLatestMessageChain(local);
  if (
    first?.parentNodeId == null ||
    !localChain.some((message) => message.messageId === first.parentNodeId)
  ) {
    return {
      messageTree: saved,
      hasOlderMessages: page.has_older_messages ?? false,
    };
  }

  // Live nodes can still use temporary IDs; saved links use database IDs.
  const nodeIds = new Map(
    [...local].map(([id, message]) => [id, message.messageId ?? id])
  );
  const messageTree = new Map<number, Message>();
  for (const [id, message] of local) {
    const nodeId = nodeIds.get(id) ?? id;
    messageTree.set(nodeId, {
      ...message,
      nodeId,
      parentNodeId:
        message.parentNodeId === null
          ? null
          : (nodeIds.get(message.parentNodeId) ?? message.parentNodeId),
      childrenNodeIds: message.childrenNodeIds?.map(
        (child) => nodeIds.get(child) ?? child
      ),
      latestChildNodeId:
        message.latestChildNodeId == null
          ? message.latestChildNodeId
          : (nodeIds.get(message.latestChildNodeId) ??
            message.latestChildNodeId),
    });
  }
  for (const [id, message] of saved) messageTree.set(id, message);
  const parent = messageTree.get(first.parentNodeId);
  if (parent) {
    messageTree.set(parent.nodeId, {
      ...parent,
      childrenNodeIds: [
        ...new Set([...(parent.childrenNodeIds ?? []), first.nodeId]),
      ],
      latestChildNodeId: first.nodeId,
    });
  }
  return { messageTree, hasOlderMessages: current.hasOlderMessages };
}

/** URL of a page of a chat: its last messages, or those before a message. */
export function chatPageUrl(
  sessionId: string,
  beforeMessageId?: number
): string {
  const params = new URLSearchParams({ limit: String(CHAT_PAGE_SIZE) });
  if (beforeMessageId !== undefined) {
    params.set("before_message_id", String(beforeMessageId));
  }
  return `/api/chat/get-chat-session/${sessionId}?${params}`;
}

/**
 * Loads the page of the current branch above the loaded messages and adds it
 * to the chat's message tree. Does nothing while a page is loading or when the
 * branch has no older messages.
 */
export async function loadOlderChatMessages(sessionId: string): Promise<void> {
  const store = useChatSessionStore.getState();
  const session = store.sessions.get(sessionId);
  if (!session?.hasOlderMessages || session.isLoadingOlderMessages) return;

  const oldest = getLatestMessageChain(session.messageTree)[0];
  if (oldest?.messageId === undefined || oldest.messageId === null) return;

  store.updateSessionData(sessionId, { isLoadingOlderMessages: true });
  try {
    const response = await fetch(chatPageUrl(sessionId, oldest.messageId));
    if (!response.ok) {
      throw new Error(`Failed to load older messages: ${response.status}`);
    }
    const page: BackendChatSession = await response.json();

    // The chat may have been dropped from the store meanwhile.
    const current = useChatSessionStore.getState().sessions.get(sessionId);
    if (!current) return;

    // An empty page: the oldest loaded message is no longer on the server's
    // branch (it was switched elsewhere, for example in another tab). Load
    // that branch instead.
    if (page.messages.length === 0) {
      void reloadLatestChatPage(sessionId);
      return;
    }

    // The tree was replaced meanwhile (a reload or a branch switch): the
    // page no longer attaches to it. The loader asks again for the new tree.
    const head = getLatestMessageChain(current.messageTree)[0];
    if (head?.messageId !== oldest.messageId) return;

    // Loaded messages win over the page's copies (the page repeats the
    // children of its last message, the first loaded ones among them).
    const olderMessages = processRawChatHistory(page.messages, page.packets);
    useChatSessionStore
      .getState()
      .updateSessionMessageTree(
        sessionId,
        new Map([...olderMessages, ...current.messageTree])
      );
    useChatSessionStore.getState().updateSessionData(sessionId, {
      hasOlderMessages: page.has_older_messages ?? false,
    });
  } catch (error) {
    console.error("Failed to load older chat messages", { sessionId, error });
    // Stop loading older pages, so a failing request does not repeat while
    // the loader stays in view. Reopening the chat tries again.
    if (useChatSessionStore.getState().sessions.has(sessionId)) {
      useChatSessionStore
        .getState()
        .updateSessionData(sessionId, { hasOlderMessages: false });
    }
  } finally {
    if (useChatSessionStore.getState().sessions.has(sessionId)) {
      useChatSessionStore
        .getState()
        .updateSessionData(sessionId, { isLoadingOlderMessages: false });
    }
  }
}

/**
 * Replaces the chat's message tree with the last page of its current branch,
 * for example after a switch to a branch whose messages are not loaded. Does
 * nothing if the latest message changed while the page loaded.
 */
export async function reloadLatestChatPage(sessionId: string): Promise<void> {
  const tailAtStart = latestMessageNodeId(sessionId);
  try {
    const response = await fetch(chatPageUrl(sessionId));
    if (!response.ok) {
      throw new Error(`Failed to reload the chat: ${response.status}`);
    }
    const page: BackendChatSession = await response.json();
    const store = useChatSessionStore.getState();
    // The latest message changed meanwhile (for example, a message was
    // sent): keep the chat. An older page merged above does not count.
    if (
      !store.sessions.has(sessionId) ||
      latestMessageNodeId(sessionId) !== tailAtStart
    ) {
      return;
    }

    store.updateSessionMessageTree(
      sessionId,
      processRawChatHistory(page.messages, page.packets)
    );
    store.updateSessionData(sessionId, {
      hasOlderMessages: page.has_older_messages ?? false,
    });
  } catch (error) {
    console.error("Failed to reload the chat", { sessionId, error });
  }
}

/** Node id of the last message of the chat's current branch. */
function latestMessageNodeId(sessionId: string): number | undefined {
  const tree = useChatSessionStore
    .getState()
    .sessions.get(sessionId)?.messageTree;
  return tree ? getLatestMessageChain(tree).at(-1)?.nodeId : undefined;
}
