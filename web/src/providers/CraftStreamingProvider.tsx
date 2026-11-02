"use client";

import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useState,
} from "react";
import { useShallow } from "zustand/react/shallow";
import { usePathname } from "next/navigation";
import { CRAFT_PATH } from "@/app/craft/v1/constants";
import { useBuildStreaming } from "@/app/craft/hooks/useBuildStreaming";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { useUser } from "@/providers/UserProvider";

type CraftStreamingActions = ReturnType<typeof useBuildStreaming>;

const CraftStreamingContext = createContext<CraftStreamingActions | undefined>(
  undefined
);

export function CraftStreamingProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, userResolution } = useUser();
  const pathname = usePathname();
  const userId = user?.id ?? null;
  const [ownerId, setOwnerId] = useState(userId);
  const actions = useBuildStreaming({
    isEnabled: userId !== null && ownerId === userId,
  });
  const watchedSessions = useBuildSessionStore(
    useShallow((state) =>
      Array.from(state.sessions.values())
        .filter(
          (session) =>
            session.activeTurnId !== null &&
            !session.activeTurnLocalOwner &&
            ((pathname === CRAFT_PATH &&
              state.currentSessionId === session.id) ||
              session.queuedMessages.length > 0)
        )
        .map((session) => session.id)
    )
  );

  useLayoutEffect(() => {
    if (
      ownerId === userId ||
      (userId === null && userResolution !== "resolved")
    )
      return;
    if (userId !== null) {
      if (ownerId !== null) {
        window.location.reload();
        return;
      }
      setOwnerId(userId);
      return;
    }
    if (ownerId !== null) {
      const store = useBuildSessionStore.getState();
      store.cleanupOldSessions(0);
      store.setCurrentSession(null);
    }
  }, [ownerId, userId, userResolution]);

  return (
    <CraftStreamingContext.Provider value={actions}>
      {children}
      {userId !== null &&
        ownerId === userId &&
        watchedSessions.map((sessionId) => (
          <CraftTurnAttachment key={sessionId} sessionId={sessionId} />
        ))}
    </CraftStreamingContext.Provider>
  );
}

function CraftTurnAttachment({ sessionId }: { sessionId: string }) {
  const { streamTurnEvents } = useCraftStreaming();
  const turnId = useBuildSessionStore(
    (state) => state.sessions.get(sessionId)?.activeTurnId
  );
  const instanceId = useBuildSessionStore(
    (state) => state.sessions.get(sessionId)?.instanceId
  );
  const generation = useBuildSessionStore(
    (state) => state.sessions.get(sessionId)?.turnGeneration
  );
  const isInterrupting = useBuildSessionStore(
    (state) => state.sessions.get(sessionId)?.isInterrupting
  );
  useEffect(() => {
    if (!turnId || isInterrupting) return;
    const controller = new AbortController();
    void streamTurnEvents(sessionId, turnId, controller.signal);
    return () => controller.abort();
  }, [
    sessionId,
    turnId,
    instanceId,
    generation,
    isInterrupting,
    streamTurnEvents,
  ]);
  return null;
}

export function useCraftStreaming(): CraftStreamingActions {
  const context = useContext(CraftStreamingContext);
  if (context === undefined)
    throw new Error(
      "useCraftStreaming must be used within CraftStreamingProvider"
    );
  return context;
}
