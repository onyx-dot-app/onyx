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
import type { ReasoningEffortOverride } from "@/lib/languageModels/types";
import {
  User,
  UserPersonalization,
  ThemePreference,
  Permission,
} from "@/lib/types";
import { hasAnyAdminPermission } from "@/lib/permissions";
import { usePostHog } from "posthog-js/react";
import { isAuthStatusError } from "@/lib/fetcher";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/lib/users/hooks";
import { useAuthTypeMetadata, useTokenRefresh } from "@/lib/auth/hooks";
import { AuthTypeMetadata } from "@/lib/auth/types";
import {
  updateUserPersonalization as persistPersonalization,
  setUserDefaultModel,
} from "@/lib/users/svc";
import { useTheme } from "next-themes";

const EMPTY_PERMISSIONS: string[] = [];

// Auth failures skip SWR's retry but are usually transient refresh races. SWR's backoff owns the rest.
const ME_RETRY_DELAYS_MS = [2_000, 5_000, 15_000];

// Ceiling on reporting loading for a failing /api/me, so the account menu always comes back.
const ME_LOADING_DEADLINE_MS = 30_000;

/** Only "resolved" lets a null user mean signed out. "unavailable" means /api/me keeps failing for a possibly valid session. */
export type UserResolution = "loading" | "unavailable" | "resolved";

export interface UserContextType {
  user: User | null;
  userResolution: UserResolution;
  isAdmin: boolean;
  hasAdminAccess: boolean;
  permissions: string[];
  // Coarse admin-reach set: effective tokens plus the scoped manager bundle. Feeds
  // nav/page gates so a group manager is included; org-wide checks still use isAdmin.
  adminCapabilities: string[];
  // True only while /api/me is in flight. `user === null` won't do: it also means signed out.
  isUserLoading: boolean;
  refreshUser: () => Promise<void>;
  isCloudSuperuser: boolean;
  authTypeMetadata: AuthTypeMetadata | undefined;
  updateUserAutoScroll: (autoScroll: boolean) => Promise<void>;
  updateUserShortcuts: (enabled: boolean) => Promise<void>;
  updateUserPasteAsTile: (enabled: boolean) => Promise<void>;
  toggleAgentPinnedStatus: (
    currentPinnedAgentIDs: number[],
    agentId: number,
    isPinned: boolean
  ) => Promise<boolean>;
  updateUserTemperatureOverrideEnabled: (enabled: boolean) => Promise<void>;
  updateUserTemperatureDefault: (value: number | null) => Promise<void>;
  updateUserReasoningEffortDefault: (
    value: ReasoningEffortOverride | null
  ) => Promise<void>;
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
  const { user: fetchedUser, mutateUser, userError } = useCurrentUser();
  // undefined = in flight. An error counts as resolved, so a failed load fails closed.
  const isUserLoading = fetchedUser === undefined && userError === undefined;
  // Permissions read the fetch result, not `upToDateUser`: that copy lands one render late,
  // so a page gate could see empty permissions after `isUserLoading` went false and redirect.
  const authUser = fetchedUser ?? null;
  const { authTypeMetadata, isLoading: authTypeMetadataLoading } =
    useAuthTypeMetadata();
  const updatedSettingsData = useSettings();
  const posthog = usePostHog();

  // For auto_scroll and temperature_override_enabled:
  // - If user has a preference set, use that
  // - Otherwise, use the workspace setting if available
  const wsAutoScroll = updatedSettingsData.auto_scroll;
  const wsTemperatureOverride =
    updatedSettingsData.temperature_override_enabled;

  const mergeUserPreferences = useCallback(
    (currentUser: User | null): User | null => {
      if (!currentUser) return null;
      return {
        ...currentUser,
        preferences: {
          ...currentUser.preferences,
          auto_scroll:
            currentUser.preferences?.auto_scroll ?? wsAutoScroll ?? false,
          temperature_override_enabled:
            currentUser.preferences?.temperature_override_enabled ??
            wsTemperatureOverride ??
            true,
        },
      };
    },
    [wsAutoScroll, wsTemperatureOverride]
  );

  const [upToDateUser, setUpToDateUser] = useState<User | null>(null);

  useEffect(() => {
    setUpToDateUser(mergeUserPreferences(fetchedUser ?? null));
  }, [fetchedUser, mergeUserPreferences]);

  const [meRetriesExhausted, setMeRetriesExhausted] = useState(false);

  const meRetryCountRef = useRef(0);
  const meFirstErrorAtRef = useRef<number | null>(null);
  useEffect(() => {
    if (!userError) {
      meRetryCountRef.current = 0;
      meFirstErrorAtRef.current = null;
      setMeRetriesExhausted(false);
      return;
    }
    meFirstErrorAtRef.current ??= Date.now();
    if (!isAuthStatusError(userError)) {
      // SWR's backoff owns non-auth retries. Bound only how long we report loading.
      const remaining =
        ME_LOADING_DEADLINE_MS - (Date.now() - meFirstErrorAtRef.current);
      if (remaining <= 0) {
        setMeRetriesExhausted(true);
        return;
      }
      const deadlineId = setTimeout(
        () => setMeRetriesExhausted(true),
        remaining
      );
      return () => clearTimeout(deadlineId);
    }
    // Fresh error identity per failure advances the schedule. The count moves in the timer, so StrictMode is safe.
    const attempt = meRetryCountRef.current;
    const delay = ME_RETRY_DELAYS_MS[attempt];
    if (delay === undefined) {
      setMeRetriesExhausted(true);
      return;
    }
    const timeoutId = setTimeout(() => {
      meRetryCountRef.current = attempt + 1;
      void mutateUser();
    }, delay);
    return () => clearTimeout(timeoutId);
  }, [userError, mutateUser]);

  const awaitingMe = fetchedUser === undefined && !meRetriesExhausted;
  const mergePending = fetchedUser != null && upToDateUser === null;
  const userResolution: UserResolution =
    awaitingMe || mergePending
      ? "loading"
      : fetchedUser === undefined
        ? "unavailable"
        : "resolved";

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
  useTokenRefresh(upToDateUser, authTypeMetadataLoading, onRefreshFail);

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

  const updateUserTemperatureDefault = async (value: number | null) => {
    try {
      setUpToDateUser((prevUser) => {
        if (prevUser) {
          return {
            ...prevUser,
            preferences: {
              ...prevUser.preferences,
              temperature_default: value,
            },
          };
        }
        return prevUser;
      });

      const response = await fetch(`/api/temperature-default`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ temperature_default: value }),
      });

      if (!response.ok) {
        await refreshUser();
        throw new Error("Failed to update user temperature default");
      }
    } catch (error) {
      console.error("Error updating user temperature default:", error);
      throw error;
    }
  };

  const updateUserReasoningEffortDefault = async (
    value: ReasoningEffortOverride | null
  ) => {
    try {
      setUpToDateUser((prevUser) => {
        if (prevUser) {
          return {
            ...prevUser,
            preferences: {
              ...prevUser.preferences,
              reasoning_effort_default: value,
            },
          };
        }
        return prevUser;
      });

      const response = await fetch(`/api/reasoning-effort-default`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reasoning_effort_default: value }),
      });

      if (!response.ok) {
        await refreshUser();
        throw new Error("Failed to update user reasoning default");
      }
    } catch (error) {
      console.error("Error updating user reasoning default:", error);
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

  const updateUserPasteAsTile = async (enabled: boolean) => {
    try {
      setUpToDateUser((prevUser) => {
        if (prevUser) {
          return {
            ...prevUser,
            preferences: {
              ...prevUser.preferences,
              paste_as_tile: enabled,
            },
          };
        }
        return prevUser;
      });

      const response = await fetch(
        `/api/paste-as-tile?paste_as_tile=${enabled}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
        }
      );

      if (!response.ok) {
        await refreshUser();
        throw new Error("Failed to update paste tile setting");
      }
    } catch (error) {
      console.error("Error updating paste tile setting:", error);
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

      const response = await setUserDefaultModel(defaultModel);

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
        userResolution,
        refreshUser,
        authTypeMetadata,
        updateUserAutoScroll,
        updateUserShortcuts,
        updateUserPasteAsTile,
        updateUserTemperatureOverrideEnabled,
        updateUserTemperatureDefault,
        updateUserReasoningEffortDefault,
        updateUserPersonalization,
        updateUserThemePreference,
        updateUserChatBackground,
        updateUserDefaultModel,
        updateUserDefaultAppMode,
        updateUserVoiceSettings,
        toggleAgentPinnedStatus,
        isAdmin: (
          authUser?.effective_permissions ?? EMPTY_PERMISSIONS
        ).includes(Permission.FULL_ADMIN_PANEL_ACCESS),
        hasAdminAccess: hasAnyAdminPermission(
          authUser?.admin_capabilities ?? EMPTY_PERMISSIONS
        ),
        permissions: authUser?.effective_permissions ?? EMPTY_PERMISSIONS,
        adminCapabilities: authUser?.admin_capabilities ?? EMPTY_PERMISSIONS,
        isUserLoading,
        isCloudSuperuser: authUser?.is_cloud_superuser ?? false,
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
