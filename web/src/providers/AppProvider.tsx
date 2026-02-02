/**
 * AppProvider - Root Provider Composition
 *
 * This component serves as a centralized wrapper that composes all of the
 * application's context providers into a single component. It is rendered
 * at the root layout level (`app/layout.tsx`) and provides global state
 * and functionality to the entire application.
 *
 * ## Why a Wrapper?
 *
 * Instead of nesting dozens of providers in the layout file (which becomes
 * unwieldy and hard to maintain), we compose them here in a logical order.
 * This pattern:
 * - Keeps the layout file clean
 * - Makes provider dependencies explicit
 * - Allows easy addition/removal of providers
 * - Ensures consistent provider ordering across the app
 *
 * ## Provider Hierarchy (outermost to innermost)
 *
 * 1. **SettingsProvider** - Application settings and feature flags
 * 2. **UserProvider** - Current user authentication and profile
 * 3. **AppBackgroundProvider** - App background image/URL based on user preferences
 * 4. **ProviderContextProvider** - LLM provider configuration
 * 5. **ModalProvider** - Global modal state management
 * 6. **AppSidebarProvider** - Sidebar open/closed state
 * 7. **AppModeProvider** - Search/Chat mode selection
 *
 * ## Usage
 *
 * This component is used once in `app/layout.tsx`:
 *
 * ```tsx
 * <AppProvider user={user} settings={settings} authTypeMetadata={authType}>
 *   {children}
 * </AppProvider>
 * ```
 *
 * Individual providers can then be accessed via their respective hooks:
 * - `useSettingsContext()` - from SettingsProvider
 * - `useUser()` - from UserProvider
 * - `useAppBackground()` - from AppBackgroundProvider
 * - `useAppMode()` - from AppModeProvider
 * - etc.
 *
 * @TODO(@raunakab): The providers wrapped by this component are currently
 * scattered across multiple directories:
 * - `@/providers/UserProvider`
 * - `@/components/chat/ProviderContext`
 * - `@/providers/SettingsProvider`
 * - `@/components/context/ModalContext`
 * - `@/providers/AppSidebarProvider`
 *
 * These should eventually be consolidated into the `/web/src/providers`
 * directory for consistency and discoverability. This would make it clear
 * where all global state providers live.
 */
"use client";

import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { UserProvider } from "@/providers/UserProvider";
import { ProviderContextProvider } from "@/components/chat/ProviderContext";
import { SettingsProvider } from "@/providers/SettingsProvider";
import { User } from "@/lib/types";
import { ModalProvider } from "@/components/context/ModalContext";
import { AuthTypeMetadata } from "@/lib/userSS";
import { AppSidebarProvider } from "@/providers/AppSidebarProvider";
import { AppModeProvider } from "@/providers/AppModeProvider";
import { AppBackgroundProvider } from "@/providers/AppBackgroundProvider";

interface AppProviderProps {
  children: React.ReactNode;
  user: User | null;
  settings: CombinedSettings;
  authTypeMetadata: AuthTypeMetadata;
  folded?: boolean;
}

export default function AppProvider({
  children,
  user,
  settings,
  authTypeMetadata,
  folded,
}: AppProviderProps) {
  return (
    <SettingsProvider settings={settings}>
      <UserProvider
        settings={settings}
        user={user}
        authTypeMetadata={authTypeMetadata}
      >
        <AppBackgroundProvider>
          <ProviderContextProvider>
            <ModalProvider user={user}>
              <AppSidebarProvider folded={!!folded}>
                <AppModeProvider>{children}</AppModeProvider>
              </AppSidebarProvider>
            </ModalProvider>
          </ProviderContextProvider>
        </AppBackgroundProvider>
      </UserProvider>
    </SettingsProvider>
  );
}
