import { useEffect } from "react";
import { useBuildSessionStore } from "./useBuildSessionStore";

/**
 * Hook that handles pre-provisioning lifecycle.
 *
 * Automatically triggers pre-provisioning when:
 * - User is on a new build page (no current session)
 * - No pre-provisioned session exists yet
 * - No provisioning is already in progress
 *
 * Usage: Call this hook in the /build/v1 layout to enable pre-provisioning.
 */
export function usePreProvisioning() {
  const currentSessionId = useBuildSessionStore(
    (state) => state.currentSessionId
  );
  const preProvisionedSessionId = useBuildSessionStore(
    (state) => state.preProvisionedSessionId
  );
  const preProvisioningPromise = useBuildSessionStore(
    (state) => state.preProvisioningPromise
  );
  const ensurePreProvisionedSession = useBuildSessionStore(
    (state) => state.ensurePreProvisionedSession
  );

  useEffect(() => {
    const shouldProvision =
      currentSessionId === null &&
      !preProvisionedSessionId &&
      !preProvisioningPromise;

    if (shouldProvision) {
      ensurePreProvisionedSession();
    }
  }, [
    currentSessionId,
    preProvisionedSessionId,
    preProvisioningPromise,
    ensurePreProvisionedSession,
  ]);

  return {
    isPreProvisioning: !!preProvisioningPromise,
    isReady: !!preProvisionedSessionId,
  };
}
