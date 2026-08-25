/**
 * Mock for @/providers/UserProvider
 *
 * Why this mock exists:
 * The real UserProvider requires complex props (authTypeMetadata, settings, user)
 * that are not relevant for most component integration tests. This mock provides
 * a simple useUser() hook with safe default values.
 *
 * Usage:
 * Automatically applied via jest.config.js moduleNameMapper.
 * Any component that imports from "@/providers/UserProvider" will get this mock.
 *
 * To customize user values in a specific test:
 * You would need to either:
 * 1. Pass props to the real UserProvider (requires disabling this mock for that test)
 * 2. Extend this mock to accept custom values via a setup function
 *
 * The context is typed as the real `UserContextType` so a field added to the
 * provider fails the typecheck here instead of silently reaching components as
 * `undefined`. The import is type-only: a value import would resolve back to this
 * mock through moduleNameMapper and cycle.
 */
import React, { createContext, useContext } from "react";
import type { UserContextType } from "@/providers/UserProvider";

const mockUserContext: UserContextType = {
  user: null,
  userResolution: "resolved",
  isAdmin: false,
  hasAdminAccess: false,
  permissions: [],
  adminCapabilities: [],
  isUserLoading: false,
  refreshUser: async () => {},
  isCloudSuperuser: false,
  authTypeMetadata: undefined,
  updateUserAutoScroll: async () => {},
  updateUserShortcuts: async () => {},
  updateUserPasteAsTile: async () => {},
  toggleAgentPinnedStatus: async () => true,
  updateUserTemperatureOverrideEnabled: async () => {},
  updateUserPersonalization: async () => {},
  updateUserThemePreference: async () => {},
  updateUserChatBackground: async () => {},
  updateUserDefaultModel: async () => {},
  updateUserDefaultAppMode: async () => {},
  updateUserVoiceSettings: async () => {},
  updateUserTemperatureDefault: async () => {},
  updateUserReasoningEffortDefault: async () => {},
};

const UserContext = createContext<UserContextType | undefined>(mockUserContext);

export function useUser() {
  const context = useContext(UserContext);
  if (context === undefined) {
    throw new Error("useUser must be used within a UserProvider");
  }
  return context;
}

export function UserProvider({ children }: { children: React.ReactNode }) {
  return (
    <UserContext.Provider value={mockUserContext}>
      {children}
    </UserContext.Provider>
  );
}
