"use client";

import { useCallback, useState, useMemo, useEffect } from "react";
import { useUser } from "@/providers/UserProvider";
import {
  OnboardingModalMode,
  OnboardingModalController,
  BuildUserInfo,
} from "@/app/craft/onboarding/types";
import {
  getBuildUserPersona,
  setBuildUserPersona,
} from "@/app/craft/onboarding/constants";
import { updateUserPersonalization } from "@/lib/userSettings";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";

export function useOnboardingModal(): OnboardingModalController {
  const { user, isAdmin, refreshUser } = useUser();

  // Get ensurePreProvisionedSession from the session store
  const ensurePreProvisionedSession = useBuildSessionStore(
    (state) => state.ensurePreProvisionedSession
  );

  // Modal mode state
  const [mode, setMode] = useState<OnboardingModalMode>({ type: "closed" });
  const [hasInitialized, setHasInitialized] = useState(false);

  // Compute initial values for the form (read fresh on every render)
  const existingPersona = getBuildUserPersona();
  const existingName = user?.personalization?.name || "";
  const spaceIndex = existingName.indexOf(" ");
  const initialFirstName =
    spaceIndex > 0 ? existingName.slice(0, spaceIndex) : existingName;
  const initialLastName =
    spaceIndex > 0 ? existingName.slice(spaceIndex + 1) : "";

  const initialValues = {
    firstName: initialFirstName,
    lastName: initialLastName,
    workArea: existingPersona?.workArea,
    level: existingPersona?.level,
  };

  // Check if user has completed initial onboarding (only role required, not name)
  const hasUserInfo = useMemo(() => {
    return !!getBuildUserPersona()?.workArea;
  }, [user]);

  // Auto-open initial onboarding modal on first load
  // Shows if user info (role) is missing
  useEffect(() => {
    if (hasInitialized || !user) return;

    if (!hasUserInfo) {
      setMode({ type: "initial-onboarding" });
    }

    setHasInitialized(true);
  }, [hasInitialized, user, hasUserInfo]);

  // Complete user info callback
  const completeUserInfo = useCallback(
    async (info: BuildUserInfo) => {
      // Save name via API (handle optional lastName)
      const fullName = info.lastName
        ? `${info.firstName} ${info.lastName}`.trim()
        : info.firstName.trim();
      await updateUserPersonalization({ name: fullName });

      // Save persona to cookie
      setBuildUserPersona({
        workArea: info.workArea,
        level: info.level,
      });

      // Refresh user to update state
      await refreshUser();

      // Trigger pre-provisioning now that onboarding is complete
      ensurePreProvisionedSession();
    },
    [refreshUser, ensurePreProvisionedSession]
  );

  // Actions
  const openPersonaEditor = useCallback(() => {
    setMode({ type: "edit-persona" });
  }, []);

  const close = useCallback(() => {
    setMode({ type: "closed" });
  }, []);

  const isOpen = mode.type !== "closed";

  return {
    mode,
    isOpen,
    openPersonaEditor,
    close,
    initialValues,
    completeUserInfo,
    isAdmin,
    hasUserInfo,
    isLoading: false,
  };
}
