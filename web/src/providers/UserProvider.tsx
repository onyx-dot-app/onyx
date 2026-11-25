"use client";

import { useNavigation } from "@opal/navigation";
import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  useEffect,
  useRef,
} from "react";
import { useTranslations } from "next-intl";
import { toast } from "@opal/layouts";
import {
  User,
  UserPersonalization,
  UserPreferences,
  Permission,
} from "@/lib/types";
import { hasAnyAdminPermission } from "@/lib/permissions/utils";
import { usePostHog } from "posthog-js/react";
import { isAuthStatusError } from "@/lib/fetcher";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/lib/users/hooks";
import { useAuthTypeMetadata, useTokenRefresh } from "@/lib/auth/hooks";
import { AuthTypeMetadata } from "@/lib/auth/types";
import { updateUserPersonalization as persistPersonalization } from "@/lib/users/svc";
import { useTheme } from "next-themes";
import { isSupportedLocale, type Locale } from "@/i18n/config";

const EMPTY_PERMISSIONS: string[] = [];

// Auth failures skip SWR's retry but are usually transient refresh races. SWR's backoff owns the rest.
const ME_RETRY_DELAYS_MS = [2_000, 5_000, 15_000];

// Ceiling on reporting loading for a failing /api/me, so the account menu always comes back.
const ME_LOADING_DEADLINE_MS = 30_000;

/** The voice settings endpoint names its fields without the `voice_` prefix. */
interface VoiceSettingsRequestBody {
  auto_send?: boolean;
  auto_playback?: boolean;
  playback_speed?: number;
}

type PreferenceRequestBody =
  | Partial<UserPreferences>
  | VoiceSettingsRequestBody;

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
  /**
   * Saves a preference change: applies `patch` to the cached user at once,
   * sends it to `endpoint` as a PATCH with `body` (the patch by default), and
   * on failure restores the cached user and shows an error toast. Resolves to
   * whether the save succeeded.
   */
  updatePreferences: (
    patch: Partial<UserPreferences>,
    endpoint: string,
    body?: PreferenceRequestBody
  ) => Promise<boolean>;
  /** Saves only the given personalization fields; rejects on failure. */
  updateUserPersonalization: (
    patch: Partial<UserPersonalization>
  ) => Promise<void>;
  // null clears the preference so the user follows the workspace default.
  updateUserLanguage: (language: Locale | null) => Promise<void>;
}

const UserContext = createContext<UserContextType | undefined>(undefined);

export function UserProvider({ children }: { children: React.ReactNode }) {
  const { user: fetchedUser, mutateUser, userError } = useCurrentUser();
  // undefined = in flight. An error counts as resolved, so a failed load fails closed.
  const isUserLoading = fetchedUser === undefined && userError === undefined;
  const { authTypeMetadata, isLoading: authTypeMetadataLoading } =
    useAuthTypeMetadata();
  const updatedSettingsData = useSettings();
  const posthog = usePostHog();
  const t = useTranslations("settings");

  // For auto_scroll and temperature_override_enabled:
  // - If user has a preference set, use that
  // - Otherwise, use the workspace setting if available
  const wsAutoScroll = updatedSettingsData.auto_scroll;
  const wsTemperatureOverride =
    updatedSettingsData.temperature_override_enabled;

  // Derived from the SWR cache, the one client copy of the user, so
  // preference saves and /me fetches cannot overwrite each other.
  const user = useMemo((): User | null => {
    if (!fetchedUser) return null;
    return {
      ...fetchedUser,
      preferences: {
        ...fetchedUser.preferences,
        auto_scroll:
          fetchedUser.preferences?.auto_scroll ?? wsAutoScroll ?? false,
        temperature_override_enabled:
          fetchedUser.preferences?.temperature_override_enabled ??
          wsTemperatureOverride ??
          true,
      },
    };
  }, [fetchedUser, wsAutoScroll, wsTemperatureOverride]);

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
  const userResolution: UserResolution = awaitingMe
    ? "loading"
    : fetchedUser === undefined
      ? "unavailable"
      : "resolved";

  useEffect(() => {
    if (!posthog) return;

    if (fetchedUser?.id) {
      const identifyData: Record<string, string> = {
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
  const onRefreshFail = useCallback(async () => {
    await mutateUser();
  }, [mutateUser]);
  useTokenRefresh(user, authTypeMetadataLoading, onRefreshFail);

  // Sync user's theme preference from DB to next-themes on load
  const { setTheme, theme } = useTheme();
  const hasSyncedThemeRef = useRef(false);

  useEffect(() => {
    // Only sync once per session
    if (hasSyncedThemeRef.current) return;

    // Wait for next-themes to initialize
    if (!theme) return;

    // Wait for user data to load
    if (!user?.id) return;

    // Only sync if user has a saved preference
    const savedTheme = user?.preferences?.theme_preference;
    if (!savedTheme) return;

    // Sync DB theme to localStorage
    setTheme(savedTheme);
    hasSyncedThemeRef.current = true;
  }, [user?.id, user?.preferences?.theme_preference, theme, setTheme]);

  // The backend owns NEXT_LOCALE (set on PATCH /user/language, reconciled on
  // GET /me). This effect is the one place the UI catches up: whenever
  // <html lang> lags the effective language, re-fetch /me so the cookie and
  // the cached user are current, then re-render the server layout.
  const navigation = useNavigation();

  // A user without a stored language follows the workspace default, which is
  // unknown until settings load.
  const workspaceLanguage: Locale | undefined = updatedSettingsData.isLoading
    ? undefined
    : updatedSettingsData.default_language;
  const effectiveLanguage: Locale | undefined =
    user?.preferences?.language ?? workspaceLanguage;

  useEffect(() => {
    if (!isSupportedLocale(effectiveLanguage)) return;
    if (document.documentElement.lang === effectiveLanguage) return;
    mutateUser()
      .then(() => navigation.refresh())
      .catch((error: unknown) => {
        // The next successful /me resolves the drift.
        console.error("Error reconciling the UI language:", error);
      });
  }, [user?.id, effectiveLanguage, navigation, mutateUser]);

  const updatePreferences = useCallback(
    async (
      patch: Partial<UserPreferences>,
      endpoint: string,
      body: PreferenceRequestBody = patch
    ): Promise<boolean> => {
      if (!fetchedUser) return false;
      const withPatch = (current: User | null | undefined): User | null =>
        current
          ? { ...current, preferences: { ...current.preferences, ...patch } }
          : null;
      // The patch builds on the displayed user, so overlapping saves keep
      // each other's changes. The displayed user stays as the cache on
      // success; a failure shows the server's state.
      try {
        await mutateUser(
          async () => {
            const response = await fetch(endpoint, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            });
            if (!response.ok) {
              throw new Error(`PATCH ${endpoint} failed: ${response.status}`);
            }
            return undefined;
          },
          {
            optimisticData: (_committed, displayed) => withPatch(displayed),
            rollbackOnError: false,
            populateCache: false,
            revalidate: false,
          }
        );
        return true;
      } catch (error) {
        console.error("Error saving preferences:", error);
        void mutateUser();
        toast.error(t("chats.toasts.saveFailed"));
        return false;
      }
    },
    [fetchedUser, mutateUser, t]
  );

  const updateUserPersonalization = useCallback(
    async (patch: Partial<UserPersonalization>) => {
      if (!fetchedUser) throw new Error("No signed-in user");
      await mutateUser(
        async () => {
          const response = await persistPersonalization(patch);
          if (!response.ok) {
            throw new Error("Failed to update personalization settings");
          }
          return undefined;
        },
        {
          // Built on the displayed user, like updatePreferences.
          optimisticData: (_committed, displayed) =>
            displayed?.personalization
              ? {
                  ...displayed,
                  personalization: { ...displayed.personalization, ...patch },
                }
              : (displayed ?? null),
          rollbackOnError: false,
          // The refetch, also after a failure, returns the server's state,
          // including the ids of new memories.
          populateCache: false,
          revalidate: true,
        }
      );
    },
    [fetchedUser, mutateUser]
  );

  const updateUserLanguage = useCallback(
    async (language: Locale | null) => {
      await mutateUser(
        async (current) => {
          const response = await fetch(`/api/user/language`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ language }),
          });
          if (!response.ok) {
            throw new Error("Failed to update language preference");
          }
          // Applied after the PATCH so the reconcile effect never sees a
          // value the server does not hold yet.
          return current
            ? { ...current, preferences: { ...current.preferences, language } }
            : current;
        },
        { revalidate: false }
      );
    },
    [mutateUser]
  );

  const refreshUser = async () => {
    await mutateUser();
  };

  return (
    <UserContext.Provider
      value={{
        user,
        userResolution,
        refreshUser,
        authTypeMetadata,
        updatePreferences,
        updateUserPersonalization,
        updateUserLanguage,
        isAdmin: (user?.effective_permissions ?? EMPTY_PERMISSIONS).includes(
          Permission.FULL_ADMIN_PANEL_ACCESS
        ),
        hasAdminAccess: hasAnyAdminPermission(
          user?.admin_capabilities ?? EMPTY_PERMISSIONS
        ),
        permissions: user?.effective_permissions ?? EMPTY_PERMISSIONS,
        adminCapabilities: user?.admin_capabilities ?? EMPTY_PERMISSIONS,
        isUserLoading,
        isCloudSuperuser: user?.is_cloud_superuser ?? false,
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
