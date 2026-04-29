"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  useEffect,
  useRef,
} from "react";
import {
  User,
  UserPersonalization,
  UserRole,
  ThemePreference,
} from "@/lib/types";
import { usePostHog } from "posthog-js/react";
import { SettingsContext } from "@/providers/SettingsProvider";
import { useTokenRefresh } from "@/hooks/useTokenRefresh";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import {
  useAuthTypeMetadata,
  AuthTypeMetadata,
} from "@/hooks/useAuthTypeMetadata";
import { updateUserPersonalization as persistPersonalization } from "@/lib/userSettings";
import { useTheme } from "next-themes";

interface UserContextType {
  user: User | null;
  isAdmin: boolean;
  isCurator: boolean;
  refreshUser: () => Promise<void>;
  isCloudSuperuser: boolean;
  authTypeMetadata: AuthTypeMetadata;
  updateUserAutoScroll: (autoScroll: boolean) => Promise<void>;
  updateUserShortcuts: (enabled: boolean) => Promise<void>;
  toggleAgentPinnedStatus: (
    currentPinnedAgentIDs: number[],
    agentId: number,
    isPinned: boolean
  ) => Promise<boolean>;
  updateUserTemperatureOverrideEnabled: (enabled: boolean) => Promise<void>;
  updateUserPersonalization: (
    personalization: UserPersonalization
  ) => Promise<void>;
  updateUserThemePreference: (
    themePreference: ThemePreference
  ) => Promise<void>;
  updateUserChatBackground: (chatBackground: string | null) => Promise<void>;
  updateUserDefaultModel: (defaultModel: string | null) => Promise<void>;
  updateUserDefaultAppMode: (mode: "CHAT" | "SEARCH") => Promise<void>;
  updateUserVoiceSettings: (settings: {
    auto_send?: boolean;
    auto_playback?: boolean;
    playback_speed?: number;
  }) => Promise<void>;
}

const UserContext = createContext<UserContextType | undefined>(undefined);

export function UserProvider({ children }: { children: React.ReactNode }) {
  const { user: fetchedUser, mutateUser } = useCurrentUser();
  const { authTypeMetadata, isLoading: authTypeMetadataLoading } =
    useAuthTypeMetadata();
  const updatedSettings = useContext(SettingsContext);
  const posthog = usePostHog();

  // For auto_scroll and temperature_override_enabled:
  // - If user has a preference set, use that
  // - Otherwise, use the workspace setting if available
  const mergeUserPreferences = useCallback(
    (currentUser: User | null): User | null => {
      if (!currentUser) return null;
      return {
        ...currentUser,
        preferences: {
          ...currentUser.preferences,
          auto_scroll:
            currentUser.preferences?.auto_scroll ??
            updatedSettings?.settings?.auto_scroll ??
            false,
          temperature_override_enabled:
            currentUser.preferences?.temperature_override_enabled ??
            updatedSettings?.settings?.temperature_override_enabled ??
            false,
        },
      };
    },
    [updatedSettings]
  );

  const [upToDateUser, setUpToDateUser] = useState<User | null>(null);

  useEffect(() => {
    setUpToDateUser(mergeUserPreferences(fetchedUser ?? null));
  }, [fetchedUser, mergeUserPreferences]);

  useEffect(() => {
    if (!posthog) return;

    if (fetchedUser?.id) {
      const identifyData: Record<string, any> = {
        email: fetchedUser.email,
      };
      if (fetchedUser.team_name) {
        identifyData.team_name = fetchedUser.team_name;
      }
      posthog.identify(fetchedUser.id, identifyData);
    } else {
      posthog.reset();
    }
  }, [posthog, fetchedUser]);

  // Use the custom token refresh hook — on refresh failure, revalidate via SWR
  // so the result goes through mergeUserPreferences
  const onRefreshFail = useCallback(async () => {
    await mutateUser();
  }, [mutateUser]);
  useTokenRefresh(
    upToDateUser,
    authTypeMetadata,
    authTypeMetadataLoading,
    onRefreshFail
  );

  // Sync user's theme preference from DB to next-themes on load
  const { setTheme, theme } = useTheme();
  const hasSyncedThemeRef = useRef(false);

  useEffect(() => {
    // Only sync once per session
    if (hasSyncedThemeRef.current) return;

    // Wait for next-themes to initialize
    if (!theme) return;

    // Wait for user data to load
    if (!upToDateUser?.id) return;

    // Only sync if user has a saved preference
    const savedTheme = upToDateUser?.preferences?.theme_preference;
    if (!savedTheme) return;

    // Sync DB theme to localStorage
    setTheme(savedTheme);
    hasSyncedThemeRef.current = true;
  }, [
    upToDateUser?.id,
    upToDateUser?.preferences?.theme_preference,
    theme,
    setTheme,
  ]);

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

  const toggleAgentPinnedStatus = async (
    currentPinnedAgentIDs: number[],
    agentId: number,
    isPinned: boolean
  ) => {
    setUpToDateUser((prevUser) => {
      if (!prevUser) return prevUser;
      return {
        ...prevUser,
        preferences: {
          ...prevUser.preferences,
          pinned_assistants: isPinned
            ? [...currentPinnedAgentIDs, agentId]
            : currentPinnedAgentIDs.filter((id) => id !== agentId),
        },
      };
    });

    let updatedPinnedAgentsIds = isPinned
      ? [...currentPinnedAgentIDs, agentId]
      : currentPinnedAgentIDs.filter((id) => id !== agentId);
    try {
      const response = await fetch(`/api/user/pinned-assistants`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ordered_assistant_ids: updatedPinnedAgentsIds,
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

  const updateUserThemePreference = async (
    themePreference: ThemePreference
  ) => {
    try {
      setUpToDateUser((prevUser) => {
        if (prevUser) {
          return {
            ...prevUser,
            preferences: {
              ...prevUser.preferences,
              theme_preference: themePreference,
            },
          };
        }
        return prevUser;
      });

      const response = await fetch(`/api/user/theme-preference`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ theme_preference: themePreference }),
      });

      if (!response.ok) {
        await refreshUser();
        throw new Error("Failed to update theme preference");
      }
    } catch (error) {
      console.error("Error updating theme preference:", error);
      throw error;
    }
  };

  const updateUserChatBackground = async (chatBackground: string | null) => {
    try {
      setUpToDateUser((prevUser) => {
        if (prevUser) {
          return {
            ...prevUser,
            preferences: {
              ...prevUser.preferences,
              chat_background: chatBackground,
            },
          };
        }
        return prevUser;
      });

      const response = await fetch(`/api/user/chat-background`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ chat_background: chatBackground }),
      });

      if (!response.ok) {
        await refreshUser();
        throw new Error("Failed to update chat background");
      }
    } catch (error) {
      console.error("Error updating chat background:", error);
      throw error;
    }
  };

  const updateUserDefaultModel = async (defaultModel: string | null) => {
    try {
      setUpToDateUser((prevUser) => {
        if (prevUser) {
          return {
            ...prevUser,
            preferences: {
              ...prevUser.preferences,
              default_model: defaultModel,
            },
          };
        }
        return prevUser;
      });

      const response = await fetch(`/api/user/default-model`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ default_model: defaultModel }),
      });

      if (!response.ok) {
        await refreshUser();
        throw new Error("Failed to update default model");
      }
    } catch (error) {
      console.error("Error updating default model:", error);
      throw error;
    }
  };

  const updateUserDefaultAppMode = async (mode: "CHAT" | "SEARCH") => {
    try {
      setUpToDateUser((prevUser) => {
        if (prevUser) {
          return {
            ...prevUser,
            preferences: {
              ...prevUser.preferences,
              default_app_mode: mode,
            },
          };
        }
        return prevUser;
      });

      const response = await fetch("/api/user/default-app-mode", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ default_app_mode: mode }),
      });

      if (!response.ok) {
        await refreshUser();
        throw new Error("Failed to update default app mode");
      }
    } catch (error) {
      console.error("Error updating default app mode:", error);
      throw error;
    }
  };

  const updateUserVoiceSettings = async (settings: {
    auto_send?: boolean;
    auto_playback?: boolean;
    playback_speed?: number;
  }) => {
    try {
      setUpToDateUser((prevUser) => {
        if (prevUser) {
          return {
            ...prevUser,
            preferences: {
              ...prevUser.preferences,
              voice_auto_send:
                settings.auto_send ?? prevUser.preferences.voice_auto_send,
              voice_auto_playback:
                settings.auto_playback ??
                prevUser.preferences.voice_auto_playback,
              voice_playback_speed:
                settings.playback_speed ??
                prevUser.preferences.voice_playback_speed,
            },
          };
        }
        return prevUser;
      });

      const response = await fetch("/api/voice/settings", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(settings),
      });

      if (!response.ok) {
        await refreshUser();
        throw new Error("Failed to update voice settings");
      }
    } catch (error) {
      console.error("Error updating voice settings:", error);
      throw error;
    }
  };

  const refreshUser = async () => {
    await mutateUser();
  };

  return (
    <UserContext.Provider
      value={{
        user: upToDateUser,
        refreshUser,
        authTypeMetadata,
        updateUserAutoScroll,
        updateUserShortcuts,
        updateUserTemperatureOverrideEnabled,
        updateUserPersonalization,
        updateUserThemePreference,
        updateUserChatBackground,
        updateUserDefaultModel,
        updateUserDefaultAppMode,
        updateUserVoiceSettings,
        toggleAgentPinnedStatus,
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
