"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { User, UserPersonalization, UserRole } from "@/lib/types";
import { getCurrentUser } from "@/lib/user";
import { usePostHog } from "posthog-js/react";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { SettingsContext } from "../settings/SettingsProvider";
import { useTokenRefresh } from "@/hooks/useTokenRefresh";
import { AuthTypeMetadata } from "@/lib/userSS";
import { updateUserPersonalization as persistPersonalization } from "@/lib/users/UserSettings";

interface UserContextType {
  user: User | null;
  isAdmin: boolean;
  isCurator: boolean;
  refreshUser: () => Promise<void>;
  isCloudSuperuser: boolean;
  updateUserAutoScroll: (autoScroll: boolean) => Promise<void>;
  updateUserShortcuts: (enabled: boolean) => Promise<void>;
  toggleAssistantPinnedStatus: (
    currentPinnedAssistantIDs: number[],
    assistantId: number,
    isPinned: boolean
  ) => Promise<boolean>;
  updateUserTemperatureOverrideEnabled: (enabled: boolean) => Promise<void>;
  updateUserPersonalization: (
    personalization: UserPersonalization
  ) => Promise<void>;
}

const UserContext = createContext<UserContextType | undefined>(undefined);

export function UserProvider({
  authTypeMetadata,
  children,
  user,
  settings,
}: {
  authTypeMetadata: AuthTypeMetadata;
  children: React.ReactNode;
  user: User | null;
  settings: CombinedSettings;
}) {
  const updatedSettings = useContext(SettingsContext);
  const posthog = usePostHog();

  // For auto_scroll and temperature_override_enabled:
  // - If user has a preference set, use that
  // - Otherwise, use the workspace setting if available
  function mergeUserPreferences(
    currentUser: User | null,
    currentSettings: CombinedSettings | null
  ): User | null {
    if (!currentUser) return null;
    return {
      ...currentUser,
      preferences: {
        ...currentUser.preferences,
        auto_scroll:
          currentUser.preferences?.auto_scroll ??
          currentSettings?.settings?.auto_scroll ??
          false,
        temperature_override_enabled:
          currentUser.preferences?.temperature_override_enabled ??
          currentSettings?.settings?.temperature_override_enabled ??
          false,
      },
    };
  }

  const [upToDateUser, setUpToDateUser] = useState<User | null>(
    mergeUserPreferences(user, settings)
  );

  useEffect(() => {
    setUpToDateUser(mergeUserPreferences(user, updatedSettings));
  }, [user, updatedSettings]);

  useEffect(() => {
    if (!posthog) return;

    if (user?.id) {
      const identifyData: Record<string, any> = {
        email: user.email,
      };
      if (user.team_name) {
        identifyData.team_name = user.team_name;
      }
      posthog.identify(user.id, identifyData);
    } else {
      posthog.reset();
    }
  }, [posthog, user]);

  const fetchUser = async () => {
    try {
      const currentUser = await getCurrentUser();
      setUpToDateUser(currentUser);
    } catch (error) {
      console.error("Error fetching current user:", error);
    }
  };

  // Use the custom token refresh hook
  useTokenRefresh(upToDateUser, authTypeMetadata, fetchUser);

  const updateUserTemperatureOverrideEnabled = async (enabled: boolean) => {
    try {
      setUpToDateUser((prevUser) => {
        if (prevUser) {
          return {
            ...prevUser,
            preferences: {
              ...prevUser.preferences,
              temperature_override_enabled: enabled,
            },
          };
        }
        return prevUser;
      });

      const response = await fetch(
        `/api/temperature-override-enabled?temperature_override_enabled=${enabled}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
        }
      );

      if (!response.ok) {
        await refreshUser();
        throw new Error("Failed to update user temperature override setting");
      }
    } catch (error) {
      console.error("Error updating user temperature override setting:", error);
      throw error;
    }
  };

  const updateUserShortcuts = async (enabled: boolean) => {
    try {
      setUpToDateUser((prevUser) => {
        if (prevUser) {
          return {
            ...prevUser,
            preferences: {
              ...prevUser.preferences,
              shortcut_enabled: enabled,
            },
          };
        }
        return prevUser;
      });

      const response = await fetch(
        `/api/shortcut-enabled?shortcut_enabled=${enabled}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
        }
      );

      if (!response.ok) {
        await refreshUser();
        throw new Error("Failed to update user shortcut setting");
      }
    } catch (error) {
      console.error("Error updating user shortcut setting:", error);
      throw error;
    }
  };

  const updateUserAutoScroll = async (autoScroll: boolean) => {
    try {
      const response = await fetch("/api/auto-scroll", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ auto_scroll: autoScroll }),
      });
      setUpToDateUser((prevUser) => {
        if (prevUser) {
          return {
            ...prevUser,
            preferences: {
              ...prevUser.preferences,
              auto_scroll: autoScroll,
            },
          };
        }
        return prevUser;
      });

      if (!response.ok) {
        throw new Error("Failed to update auto-scroll setting");
      }
    } catch (error) {
      console.error("Error updating auto-scroll setting:", error);
      throw error;
    }
  };

  const updateUserPersonalization = async (
    personalization: UserPersonalization
  ) => {
    try {
      setUpToDateUser((prevUser) => {
        if (!prevUser) {
          return prevUser;
        }

        return {
          ...prevUser,
          personalization,
        };
      });

      const response = await persistPersonalization(personalization);

      if (!response.ok) {
        await refreshUser();
        throw new Error("Failed to update personalization settings");
      }

      await refreshUser();
    } catch (error) {
      console.error("Error updating personalization settings:", error);
      throw error;
    }
  };

  const toggleAssistantPinnedStatus = async (
    currentPinnedAssistantIDs: number[],
    assistantId: number,
    isPinned: boolean
  ) => {
    setUpToDateUser((prevUser) => {
      if (!prevUser) return prevUser;
      return {
        ...prevUser,
        preferences: {
          ...prevUser.preferences,
          pinned_assistants: isPinned
            ? [...currentPinnedAssistantIDs, assistantId]
            : currentPinnedAssistantIDs.filter((id) => id !== assistantId),
        },
      };
    });

    let updatedPinnedAssistantsIds = currentPinnedAssistantIDs;

    if (isPinned) {
      updatedPinnedAssistantsIds.push(assistantId);
    } else {
      updatedPinnedAssistantsIds = updatedPinnedAssistantsIds.filter(
        (id) => id !== assistantId
      );
    }
    try {
      const response = await fetch(`/api/user/pinned-assistants`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ordered_assistant_ids: updatedPinnedAssistantsIds,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to update pinned assistants");
      }

      await refreshUser();
      return true;
    } catch (error) {
      console.error("Error updating pinned assistants:", error);
      return false;
    }
  };

  const refreshUser = async () => {
    await fetchUser();
  };

  return (
    <UserContext.Provider
      value={{
        user: upToDateUser,
        refreshUser,
        updateUserAutoScroll,
        updateUserShortcuts,
        updateUserTemperatureOverrideEnabled,
        updateUserPersonalization,
        toggleAssistantPinnedStatus,
        isAdmin: upToDateUser?.role === UserRole.ADMIN,
        // Curator status applies for either global or basic curator
        isCurator:
          upToDateUser?.role === UserRole.CURATOR ||
          upToDateUser?.role === UserRole.GLOBAL_CURATOR,
        isCloudSuperuser: upToDateUser?.is_cloud_superuser ?? false,
      }}
    >
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  const context = useContext(UserContext);
  if (context === undefined) {
    throw new Error("useUser must be used within a UserProvider");
  }
  return context;
}
