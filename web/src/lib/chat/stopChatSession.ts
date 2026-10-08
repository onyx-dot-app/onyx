import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { settleChatSession } from "@/lib/chat/settleChatSession";

/** Stop only after a dispatched send has reached backend admission. */
export async function stopChatSession(
  sessionId: string,
  errorMessage: string
): Promise<void> {
  const store = useChatSessionStore.getState();
  const session = store.sessions.get(sessionId);
  if (
    !session ||
    session.chatState === "input" ||
    session.chatState === "cancelling"
  )
    return;

  const { abortController: controller, sendAcknowledged } = session;
  const ownsStop = () => {
    const current = useChatSessionStore.getState().sessions.get(sessionId);
    return (
      current?.abortController === controller &&
      current.chatState === "cancelling"
    );
  };
  store.updateChatState(sessionId, "cancelling");
  // Abort local preparation; a dispatched send must acknowledge before Stop.
  if (!sendAcknowledged) controller.abort();

  try {
    const streamId = await sendAcknowledged;
    if (!ownsStop()) return;
    if (streamId !== null) {
      const query = streamId === undefined ? "" : `?stream_id=${streamId}`;
      const response = await fetch(
        `/api/chat/stop-chat-session/${sessionId}${query}`,
        { method: "POST", signal: AbortSignal.timeout(10_000) }
      );
      if (!response.ok)
        throw new Error(`Failed to stop chat session: ${response.statusText}`);
    }
    if (!ownsStop()) return;
    await settleChatSession({ sessionId, controller, errorMessage });
  } catch (error) {
    if (!ownsStop()) return;
    useChatSessionStore.getState().updateSessionData(sessionId, {
      chatState: "unconfirmed",
      queuedMessagesPaused: true,
      uncaughtError: errorMessage,
    });
    throw error;
  }
}
