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
 * 6. **SidebarStateProvider** - Sidebar open/closed state
 * 7. **QueryControllerProvider** - Search/Chat mode + query lifecycle
 */

"use client";

import { useState } from "react";
import Cookies from "js-cookie";
import { UserProvider } from "@/providers/UserProvider";
import { ProviderContextProvider } from "@/components/chat/ProviderContext";
import { SettingsProvider } from "@/providers/SettingsProvider";
import { ModalProvider } from "@/components/context/ModalContext";
import { SidebarStateProvider } from "@opal/layouts";
import { AppBackgroundProvider } from "@/providers/AppBackgroundProvider";
import { QueryControllerProvider } from "@/providers/QueryControllerProvider";
import ToastProvider from "@/providers/ToastProvider";
import { FullWidthChatProvider } from "@/providers/FullWidthChatProvider";

interface SidebarPersistenceProviderProps {
  children: React.ReactNode;
}

function SidebarPersistenceProvider({
  children,
}: SidebarPersistenceProviderProps) {
  const [defaultFolded] = useState(() => {
    if (typeof window === "undefined") return false;
    return (
      Cookies.get("sidebarIsToggled") === "true" ||
      localStorage.getItem("sidebarIsToggled") === "true"
    );
  });

  function handleFoldedChange(folded: boolean) {
    const value = folded.toString();
    Cookies.set("sidebarIsToggled", value, { expires: 365 });
    localStorage.setItem("sidebarIsToggled", value);
  }

  return (
    <SidebarStateProvider
      defaultFolded={defaultFolded}
      onFoldedChange={handleFoldedChange}
    >
      {children}
    </SidebarStateProvider>
  );
}

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
              <SidebarPersistenceProvider>
                <QueryControllerProvider>
                  <FullWidthChatProvider>
                    <ToastProvider>{children}</ToastProvider>
                  </FullWidthChatProvider>
                </QueryControllerProvider>
              </SidebarPersistenceProvider>
            </ModalProvider>
          </ProviderContextProvider>
        </AppBackgroundProvider>
      </UserProvider>
    </SettingsProvider>
  );
}
