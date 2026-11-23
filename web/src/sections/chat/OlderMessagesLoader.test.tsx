import { act, render, waitFor } from "@tests/setup/test-utils";
import OlderMessagesLoader from "@/sections/chat/OlderMessagesLoader";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { DynamicConversationsContext } from "@/providers/AppearancePreferencesProvider";

let olderPages = 0;
jest.mock("@/lib/chat/pagedSession", () => ({
  loadOlderChatMessages: async (sessionId: string) => {
    const store = useChatSessionStore.getState();
    if (
      olderPages === 0 ||
      store.sessions.get(sessionId)?.isLoadingOlderMessages
    )
      return;
    store.updateSessionData(sessionId, { isLoadingOlderMessages: true });
    await Promise.resolve();
    olderPages -= 1;
    store.updateSessionData(sessionId, {
      isLoadingOlderMessages: false,
      hasOlderMessages: olderPages > 0,
    });
  },
}));

test("with dynamic conversations off, every older page loads without a scroll", async () => {
  olderPages = 3;
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  act(() => {
    const store = useChatSessionStore.getState();
    store.createSession("session", { hasOlderMessages: true });
    store.setCurrentSession("session");
  });

  // Outside a chat scroll container: nothing reports the loader near the
  // viewport.
  render(
    <DynamicConversationsContext.Provider value={false}>
      <OlderMessagesLoader />
    </DynamicConversationsContext.Provider>
  );

  await waitFor(() => expect(olderPages).toBe(0));
});
