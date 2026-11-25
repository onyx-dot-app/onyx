import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { loadOlderChatMessages } from "@/lib/chat/pagedSession";

/** The most older pages one search loads. */
export const FIND_MAX_OLDER_PAGES = 20;

function olderPagesState(sessionId: string) {
  const session = useChatSessionStore.getState().sessions.get(sessionId);
  return {
    hasOlder: session?.hasOlderMessages ?? false,
    loading: session?.isLoadingOlderMessages ?? false,
    // A failed page turns `hasOlder` off, but the messages are still missing.
    missing:
      (session?.hasOlderMessages ?? false) ||
      (session?.olderMessagesFailed ?? false),
  };
}

/** Resolves once no older page of the chat is loading. */
function pageLoadSettled(sessionId: string): Promise<void> {
  if (!olderPagesState(sessionId).loading) return Promise.resolve();
  return new Promise((resolve) => {
    const unsubscribe = useChatSessionStore.subscribe(() => {
      if (olderPagesState(sessionId).loading) return;
      unsubscribe();
      resolve();
    });
  });
}

/**
 * Loads the chat's older pages one by one, so find searches the whole chat.
 * Stops after `maxPages`, when `cancelled` turns true, when none are left, or
 * when a page fails to load. Returns whether older messages are still missing.
 */
export async function loadOlderPagesForFind(
  sessionId: string,
  cancelled: () => boolean,
  maxPages = FIND_MAX_OLDER_PAGES
): Promise<boolean> {
  for (let page = 0; page < maxPages; page++) {
    // The scroll loader may be loading a page already.
    await pageLoadSettled(sessionId);
    if (cancelled()) return false;
    if (!olderPagesState(sessionId).hasOlder) break;
    await loadOlderChatMessages(sessionId);
  }
  await pageLoadSettled(sessionId);
  return olderPagesState(sessionId).missing;
}
