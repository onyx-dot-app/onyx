"use client";

import { useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { usePreProvisionPolling } from "@/app/craft/hooks/usePreProvisionPolling";
import { CRAFT_SEARCH_PARAM_NAMES } from "@/app/craft/services/searchParams";
import { CRAFT_PATH } from "@/app/craft/v1/constants";
import { getBuildUserPersona } from "@/app/craft/onboarding/constants";
import { useLLMProviders } from "@/hooks/useLLMProviders";
import { checkPreProvisionedSession } from "@/app/craft/services/apiServices";

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
 * - Re-validate pre-provisioned session on tab focus (multi-tab support)
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

  // Check if user has completed onboarding (persona cookie is set)
  // Read directly from cookie on every render - cookie reads are cheap and this
  // ensures we always have the current value, especially important after onboarding
  // completes when the cookie is set synchronously but other state updates are async
  const hasCompletedOnboarding = getBuildUserPersona() !== null;

  // Track previous existingSessionId to detect navigation transitions
  const prevExistingSessionIdRef = useRef<string | null>(existingSessionId);

  // Access store state and actions individually like chat does
  const currentSessionId = useBuildSessionStore(
    (state) => state.currentSessionId
  );
  const setCurrentSession = useBuildSessionStore(
    (state) => state.setCurrentSession
  );
  const loadSession = useBuildSessionStore((state) => state.loadSession);

  // Controller state from Zustand (replaces refs for better race condition handling)
  const controllerState = useBuildSessionStore(
    (state) => state.controllerState
  );
  const setControllerTriggered = useBuildSessionStore(
    (state) => state.setControllerTriggered
  );
  const setControllerLoaded = useBuildSessionStore(
    (state) => state.setControllerLoaded
  );

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
    const prevExistingSessionId = prevExistingSessionIdRef.current;
    prevExistingSessionIdRef.current = existingSessionId;

    // Handle navigation to "new build" (no session ID in URL)
    if (existingSessionId === null) {
      // Clear current session
      if (currentSessionId !== null) {
        setCurrentSession(null);
      }

      // Reset state when transitioning FROM a session TO new build
      // This ensures we fetch fresh pre-provisioned status from backend
      if (prevExistingSessionId !== null) {
        setControllerTriggered(null);
        // Clear pre-provisioned state to force a fresh check from backend
        useBuildSessionStore.setState({ preProvisioning: { status: "idle" } });
      }

      // Trigger pre-provisioning if conditions are met
      const canTrigger =
        controllerState.lastTriggeredForUrl !== "new-build" &&
        (preProvisioning.status === "idle" ||
          preProvisioning.status === "failed") &&
        hasCompletedOnboarding &&
        hasAnyProvider;

      // Also trigger retry if failed and retry time has passed
      const shouldRetry =
        preProvisioning.status === "failed" &&
        Date.now() >= preProvisioning.retryAt &&
        hasCompletedOnboarding &&
        hasAnyProvider;

      if (canTrigger || shouldRetry) {
        setControllerTriggered("new-build");
        ensurePreProvisionedSession();
      }
      return;
    }

    // Navigating to a session - reset the trigger state for next new build visit
    if (controllerState.lastTriggeredForUrl === "new-build") {
      setControllerTriggered(null);
    }

    // Handle navigation to existing session
    async function fetchSession() {
      if (!existingSessionId) return;

      // Mark as loaded BEFORE any async work to prevent duplicate calls
      setControllerLoaded(existingSessionId);

      // Access sessions via getState() to avoid dependency on Map reference
      const currentState = useBuildSessionStore.getState();
      const cachedSession = currentState.sessions.get(existingSessionId);

      if (cachedSession?.isLoaded) {
        // Just switch to it
        setCurrentSession(existingSessionId);
        return;
      }

      // Need to load from API
      await loadSession(existingSessionId);
    }

    // Only fetch if we haven't already loaded this session
    const currentState = useBuildSessionStore.getState();
    const currentSessionData = currentState.currentSessionId
      ? currentState.sessions.get(currentState.currentSessionId)
      : null;
    // Only block loading during active LLM streaming ("running").
    // "creating" means sandbox restore, which should not prevent
    // navigating to and loading a different session.
    const isCurrentlyStreaming = currentSessionData?.status === "running";

    if (
      controllerState.loadedSessionId !== existingSessionId &&
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
    controllerState.lastTriggeredForUrl,
    controllerState.loadedSessionId,
    setControllerTriggered,
    setControllerLoaded,
  ]);

  // Effect: Auto-retry provisioning after backoff period
  // When provisioning fails, we set a retryAt timestamp. This effect schedules
  // a timer to retry after the backoff period elapses.
  useEffect(() => {
    // Only set up timer if in failed state and on new-build page
    if (
      preProvisioning.status !== "failed" ||
      existingSessionId !== null ||
      !hasCompletedOnboarding ||
      !hasAnyProvider
    ) {
      return;
    }

    const msUntilRetry = preProvisioning.retryAt - Date.now();

    // If retry time has already passed, trigger immediately
    if (msUntilRetry <= 0) {
      console.info("[PreProvision] Retry time passed, retrying now...");
      ensurePreProvisionedSession();
      return;
    }

    // Schedule retry after backoff period
    console.info(
      `[PreProvision] Scheduling retry in ${Math.round(msUntilRetry / 1000)}s`
    );
    const timerId = setTimeout(() => {
      console.info("[PreProvision] Backoff elapsed, retrying...");
      ensurePreProvisionedSession();
    }, msUntilRetry);

    return () => clearTimeout(timerId);
  }, [
    preProvisioning,
    existingSessionId,
    hasCompletedOnboarding,
    hasAnyProvider,
    ensurePreProvisionedSession,
  ]);

  // Effect: Re-validate pre-provisioned session on tab focus (multi-tab support)
  // Uses checkPreProvisionedSession API to validate without resetting state,
  // which prevents unnecessary cascading effects when session is still valid.
  useEffect(() => {
    const handleFocus = async () => {
      const { preProvisioning } = useBuildSessionStore.getState();

      // Only re-validate if we have a "ready" pre-provisioned session
      if (preProvisioning.status === "ready") {
        const cachedSessionId = preProvisioning.sessionId;

        try {
          // Check if session is still valid WITHOUT resetting state
          const { valid } = await checkPreProvisionedSession(cachedSessionId);

          if (!valid) {
            // Session was consumed by another tab - now reset and re-provision
            console.info(
              `[PreProvision] Session ${cachedSessionId.slice(
                0,
                8
              )} invalidated on focus, re-provisioning...`
            );
            useBuildSessionStore.setState({
              preProvisioning: { status: "idle" },
            });
            const newSessionId = await useBuildSessionStore
              .getState()
              .ensurePreProvisionedSession();

            if (newSessionId) {
              console.info(
                `[PreProvision] Session changed on focus: ${cachedSessionId.slice(
                  0,
                  8
                )} -> ${newSessionId.slice(0, 8)}`
              );
            }
          }
          // If valid, do nothing - keep the current session
        } catch (error) {
          // On error, log but don't reset - better to keep potentially stale session
          // than to cause UI flicker on network blip
          console.warn(
            "[PreProvision] Failed to validate session on focus:",
            error
          );
        }
      }
    };

    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, []);

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

  // Poll to verify pre-provisioned session is still valid (multi-tab support)
  // Only poll on welcome page (existingSessionId === null) - no point polling on session pages
  usePreProvisionPolling({ enabled: existingSessionId === null });

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
