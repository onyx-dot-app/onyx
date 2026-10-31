import type { BackendChatSession } from "@/app/app/types";
import { processRawChatHistory } from "@/app/app/services/lib";
import { getLatestMessageChain } from "@/app/app/services/messageTree";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";

/** Messages of the current branch that one page of a chat holds. */
export const CHAT_PAGE_SIZE = 20;

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
    useChatSessionStore
      .getState()
      .updateSessionData(sessionId, { hasOlderMessages: false });
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
 * nothing if the tree changed while the page loaded.
 */
export async function reloadLatestChatPage(sessionId: string): Promise<void> {
  const treeAtStart = useChatSessionStore
    .getState()
    .sessions.get(sessionId)?.messageTree;
  try {
    const response = await fetch(chatPageUrl(sessionId));
    if (!response.ok) {
      throw new Error(`Failed to reload the chat: ${response.status}`);
    }
    const page: BackendChatSession = await response.json();
    const store = useChatSessionStore.getState();
    const session = store.sessions.get(sessionId);
    // The chat changed meanwhile (for example, a message was sent): keep it.
    if (!session || session.messageTree !== treeAtStart) return;

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
