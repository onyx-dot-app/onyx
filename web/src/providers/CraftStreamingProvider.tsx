"use client";

import { createContext, useContext, useLayoutEffect, useState } from "react";
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
  const userId = user?.id ?? null;
  const [ownerId, setOwnerId] = useState(userId);
  const actions = useBuildStreaming({
    isEnabled: userId !== null && ownerId === userId,
  });

  useLayoutEffect(() => {
    if (
      ownerId === userId ||
      (userId === null && userResolution !== "resolved")
    )
      return;
    if (ownerId !== null) {
      const store = useBuildSessionStore.getState();
      store.cleanupOldSessions(0);
      store.setCurrentSession(null);
    }
    setOwnerId(userId);
  }, [ownerId, userId, userResolution]);

  return (
    <CraftStreamingContext.Provider value={actions}>
      {children}
    </CraftStreamingContext.Provider>
  );
}

export function useCraftStreaming(): CraftStreamingActions {
  const context = useContext(CraftStreamingContext);
  if (context === undefined)
    throw new Error(
      "useCraftStreaming must be used within CraftStreamingProvider"
    );
  return context;
}
