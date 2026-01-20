"use client";

import { useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useBuildSessionStore } from "@/app/build/hooks/useBuildSessionStore";
import { BUILD_SEARCH_PARAM_NAMES } from "@/app/build/services/searchParams";

interface UseBuildSessionControllerProps {
  /** Session ID from search params, or null for new session */
  existingSessionId: string | null;
}

/**
 * Controller hook for managing build session lifecycle based on URL.
 * Mirrors useChatSessionController pattern.
 *
 * Responsibilities:
 * - Load session from API when URL changes
 * - Switch current session based on URL
 * - Abort active streams when navigating away
 * - Track session loading state
 */
export function useBuildSessionController({
  existingSessionId,
}: UseBuildSessionControllerProps) {
  const router = useRouter();

  // Refs to track previous session state
  const priorSessionIdRef = useRef<string | null>(null);
  const loadedSessionIdRef = useRef<string | null>(null);

  // Access store state and actions individually like chat does
  const currentSessionId = useBuildSessionStore(
    (state) => state.currentSessionId
  );
  const setCurrentSession = useBuildSessionStore(
    (state) => state.setCurrentSession
  );
  const loadSession = useBuildSessionStore((state) => state.loadSession);
  const abortSession = useBuildSessionStore((state) => state.abortSession);

  // Compute derived state directly in selectors for efficiency
  const isLoading = useBuildSessionStore((state) => {
    if (!state.currentSessionId) return false;
    const session = state.sessions.get(state.currentSessionId);
    return session ? !session.isLoaded : false;
  });

  const isStreaming = useBuildSessionStore((state) => {
    if (!state.currentSessionId) return false;
    const session = state.sessions.get(state.currentSessionId);
    return session?.status === "running" || session?.status === "creating";
  });

  // Effect: Handle session changes based on URL
  useEffect(() => {
    const priorSessionId = priorSessionIdRef.current;
    priorSessionIdRef.current = existingSessionId;

    const isNavigatingToNewSession =
      priorSessionId !== null && existingSessionId === null;
    const isSwitchingBetweenSessions =
      priorSessionId !== null &&
      existingSessionId !== null &&
      priorSessionId !== existingSessionId;

    // Abort prior session's stream when switching away
    if (
      (isNavigatingToNewSession || isSwitchingBetweenSessions) &&
      priorSessionId
    ) {
      abortSession(priorSessionId);
    }

    // Handle navigation to "new build" (no session ID)
    if (existingSessionId === null) {
      setCurrentSession(null);
      return;
    }

    // Handle navigation to existing session
    async function fetchSession() {
      if (!existingSessionId) return;

      // Access sessions via getState() to avoid dependency on Map reference
      const currentState = useBuildSessionStore.getState();
      const cachedSession = currentState.sessions.get(existingSessionId);

      if (cachedSession?.isLoaded) {
        // Just switch to it
        setCurrentSession(existingSessionId);
        loadedSessionIdRef.current = existingSessionId;
        return;
      }

      // Need to load from API
      await loadSession(existingSessionId);
      loadedSessionIdRef.current = existingSessionId;
    }

    // Only fetch if we haven't already loaded this session
    // Access current session via getState() to avoid dependency on object reference
    const currentState = useBuildSessionStore.getState();
    const currentSessionData = currentState.currentSessionId
      ? currentState.sessions.get(currentState.currentSessionId)
      : null;
    const isCurrentlyStreaming =
      currentSessionData?.status === "running" ||
      currentSessionData?.status === "creating";

    if (
      loadedSessionIdRef.current !== existingSessionId &&
      !isCurrentlyStreaming
    ) {
      fetchSession();
    } else if (currentSessionId !== existingSessionId) {
      // Session is cached, just switch to it
      setCurrentSession(existingSessionId);
    }
  }, [
    existingSessionId,
    currentSessionId,
    setCurrentSession,
    loadSession,
    abortSession,
  ]);

  /**
   * Navigate to a specific session
   */
  const navigateToSession = useCallback(
    (sessionId: string) => {
      router.push(
        `/build/v1?${BUILD_SEARCH_PARAM_NAMES.SESSION_ID}=${sessionId}`
      );
    },
    [router]
  );

  /**
   * Navigate to new build (clear session)
   */
  const navigateToNewBuild = useCallback(() => {
    if (currentSessionId) {
      abortSession(currentSessionId);
    }
    setCurrentSession(null);
    router.push("/build/v1");
  }, [currentSessionId, abortSession, setCurrentSession, router]);

  return {
    currentSessionId,
    isLoading,
    isStreaming,
    navigateToSession,
    navigateToNewBuild,
  };
}
