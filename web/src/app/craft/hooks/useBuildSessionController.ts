"use client";

import { useEffect, useRef, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { CRAFT_SEARCH_PARAM_NAMES } from "@/app/craft/services/searchParams";
import { CRAFT_PATH } from "@/app/craft/v1/constants";
import { getBuildUserPersona } from "@/app/craft/onboarding/constants";
import { useLLMProviders } from "@/lib/hooks/useLLMProviders";
import { useUser } from "@/components/user/UserProvider";

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
 * - Switch current session based on URL (single source of truth)
 * - Trigger pre-provisioning when on new build page
 * - Track session loading state
 *
 * IMPORTANT: This is the ONLY place that should call setCurrentSession.
 * Other components should navigate to URLs and let this controller handle state.
 */
export function useBuildSessionController({
  existingSessionId,
}: UseBuildSessionControllerProps) {
  const router = useRouter();

  // Check LLM provider availability
  const { llmProviders } = useLLMProviders();
  const hasAnyProvider = !!(llmProviders && llmProviders.length > 0);

  // Get user state - this updates when refreshUser() is called after onboarding
  const { user } = useUser();

  // Check if user has completed onboarding (persona cookie is set)
  // Re-evaluate when user changes (refreshUser is called after onboarding completes)
  const hasCompletedOnboarding = useMemo(() => {
    const persona = getBuildUserPersona();
    return persona !== null;
  }, [user]);

  // Refs to track previous session state
  const priorSessionIdRef = useRef<string | null>(null);
  const loadedSessionIdRef = useRef<string | null>(null);
  // Track whether we've already triggered pre-provisioning for this "new build" visit
  // Prevents re-triggering when consuming a session (state goes idle → triggers effect)
  const hasTriggeredProvisioningRef = useRef(false);

  // Access store state and actions individually like chat does
  const currentSessionId = useBuildSessionStore(
    (state) => state.currentSessionId
  );
  const setCurrentSession = useBuildSessionStore(
    (state) => state.setCurrentSession
  );
  const loadSession = useBuildSessionStore((state) => state.loadSession);

  // Pre-provisioning state (discriminated union)
  const preProvisioning = useBuildSessionStore(
    (state) => state.preProvisioning
  );
  const ensurePreProvisionedSession = useBuildSessionStore(
    (state) => state.ensurePreProvisionedSession
  );

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

  // Pre-provisioning derived state
  const isPreProvisioning = preProvisioning.status === "provisioning";
  const isPreProvisioningReady = preProvisioning.status === "ready";

  // Effect: Handle session changes based on URL
  useEffect(() => {
    const priorSessionId = priorSessionIdRef.current;
    priorSessionIdRef.current = existingSessionId;

    // Handle navigation to "new build" (no session ID in URL)
    if (existingSessionId === null) {
      // Only reset currentSessionId if we're not in the middle of consuming a pre-provisioned session
      // This prevents the race condition where we set a session and it gets immediately reset
      if (currentSessionId !== null) {
        setCurrentSession(null);
      }

      // Trigger pre-provisioning if:
      // 1. We haven't already triggered for this "visit" to new build page
      // 2. Status is idle (not already provisioning or ready)
      // 3. User has completed onboarding (persona cookie is set)
      // 4. At least one LLM provider is available
      // This prevents pre-provisioning before onboarding is complete
      if (
        !hasTriggeredProvisioningRef.current &&
        preProvisioning.status === "idle" &&
        hasCompletedOnboarding &&
        hasAnyProvider
      ) {
        hasTriggeredProvisioningRef.current = true;
        ensurePreProvisionedSession();
      }
      return;
    }

    // Navigating to a session - reset the provisioning trigger flag
    // so we can trigger again when returning to new build page
    hasTriggeredProvisioningRef.current = false;

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
    preProvisioning,
    ensurePreProvisionedSession,
    hasCompletedOnboarding,
    hasAnyProvider,
  ]);

  /**
   * Navigate to a specific session
   */
  const navigateToSession = useCallback(
    (sessionId: string) => {
      router.push(
        `${CRAFT_PATH}?${CRAFT_SEARCH_PARAM_NAMES.SESSION_ID}=${sessionId}`
      );
    },
    [router]
  );

  /**
   * Navigate to new build (clear session)
   * Note: We intentionally don't abort the current session's stream,
   * allowing it to continue in the background.
   */
  const navigateToNewBuild = useCallback(() => {
    router.push(CRAFT_PATH);
  }, [router]);

  return {
    currentSessionId,
    isLoading,
    isStreaming,
    navigateToSession,
    navigateToNewBuild,
    // Pre-provisioning state
    isPreProvisioning,
    isPreProvisioningReady,
    preProvisioning,
  };
}
