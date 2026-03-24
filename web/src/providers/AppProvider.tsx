/**
 * AppProvider - Root Provider Composition
 *
 * This component serves as a centralized wrapper that composes all of the
 * application's context providers into a single component. It is rendered
 * at the root layout level (`app/layout.tsx`) and provides global state
 * and functionality to the entire application.
 *
 * All data is fetched client-side by individual providers via SWR hooks,
 * eliminating server-side data fetching from the root layout and preventing
 * RSC prefetch amplification.
 *
 * ## Provider Hierarchy (outermost to innermost)
 *
 * 1. **SettingsProvider** - Application settings and feature flags
 * 2. **UserProvider** - Current user authentication and profile
 * 3. **AppBackgroundProvider** - App background image/URL based on user preferences
 * 4. **ProviderContextProvider** - LLM provider configuration
 * 5. **ModalProvider** - Global modal state management
 * 6. **AppSidebarProvider** - Sidebar open/closed state
 * 7. **QueryControllerProvider** - Search/Chat mode + query lifecycle
 */
"use client";

import { UserProvider } from "@/providers/UserProvider";
import { ProviderContextProvider } from "@/components/chat/ProviderContext";
import { SettingsProvider } from "@/providers/SettingsProvider";
import { ModalProvider } from "@/components/context/ModalContext";
import { AppSidebarProvider } from "@/providers/AppSidebarProvider";
import { AppBackgroundProvider } from "@/providers/AppBackgroundProvider";
import { QueryControllerProvider } from "@/providers/QueryControllerProvider";
import ToastProvider from "@/providers/ToastProvider";

interface AppProviderProps {
  children: React.ReactNode;
}

export default function AppProvider({ children }: AppProviderProps) {
  return (
    <SettingsProvider>
      <UserProvider>
        <AppBackgroundProvider>
          <ProviderContextProvider>
            <ModalProvider>
              <AppSidebarProvider>
                <QueryControllerProvider>
                  <ToastProvider>{children}</ToastProvider>
                </QueryControllerProvider>
              </AppSidebarProvider>
            </ModalProvider>
          </ProviderContextProvider>
        </AppBackgroundProvider>
      </UserProvider>
    </SettingsProvider>
  );
}
