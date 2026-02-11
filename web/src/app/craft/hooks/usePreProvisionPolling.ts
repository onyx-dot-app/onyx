"use client";

import { useEffect, useRef } from "react";
import { useBuildSessionStore } from "./useBuildSessionStore";
import { checkPreProvisionedSession } from "../services/apiServices";

/** Polling interval in milliseconds (5 seconds) */
const POLLING_INTERVAL_MS = 5000;

interface UsePreProvisionPollingOptions {
  /** Only poll when enabled (should be true only on welcome page) */
  enabled: boolean;
}

/**
 * Hook that polls to verify the pre-provisioned session is still valid.
 *
 * When multiple browser tabs have the same pre-provisioned session,
 * one tab may claim it by sending a message. This hook detects when
 * that happens and triggers re-provisioning so the current tab gets
 * a fresh session.
 *
 * Usage: Call this hook on the welcome page where pre-provisioned
 * sessions are used. Pass enabled=true only on the welcome page.
 */
export function usePreProvisionPolling({
  enabled,
}: UsePreProvisionPollingOptions) {
  const preProvisioning = useBuildSessionStore(
    (state) => state.preProvisioning
  );
  const ensurePreProvisionedSession = useBuildSessionStore(
    (state) => state.ensurePreProvisionedSession
  );

  // Extract sessionId only when status is "ready" (handles discriminated union)
  const sessionId =
    preProvisioning.status === "ready" ? preProvisioning.sessionId : null;

  // Use ref to track if we're currently checking (prevents overlapping requests)
  const isCheckingRef = useRef(false);

  useEffect(() => {
    // Only poll when enabled (welcome page) and we have a ready session
    if (!enabled || !sessionId) {
      return;
    }

    const checkValidity = async () => {
      if (isCheckingRef.current) return;
      isCheckingRef.current = true;

      try {
        const result = await checkPreProvisionedSession(sessionId);

        if (!result.valid) {
          console.log(
            `[PreProvisionPolling] Session ${sessionId.slice(
              0,
              8
            )} was used, re-provisioning...`
          );
          // Session was used by another tab - reset state and re-provision.
          // Zustand setState is synchronous, so ensurePreProvisionedSession
          // will immediately see the idle status (no setTimeout needed).
          useBuildSessionStore.setState({
            preProvisioning: { status: "idle" },
          });
          ensurePreProvisionedSession();
        }
      } catch (err) {
        console.error("[PreProvisionPolling] Failed to check session:", err);
        // On error, don't re-provision - might be a network issue
      } finally {
        isCheckingRef.current = false;
      }
    };

    // Start polling
    const intervalId = setInterval(checkValidity, POLLING_INTERVAL_MS);

    // Also check immediately on mount (in case session was used while tab was inactive)
    checkValidity();

    return () => {
      clearInterval(intervalId);
    };
  }, [enabled, sessionId, ensurePreProvisionedSession]);
}
