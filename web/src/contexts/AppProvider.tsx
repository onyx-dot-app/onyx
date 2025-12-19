"use client";

import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { UserProvider } from "@/components/user/UserProvider";
import { ProviderContextProvider } from "@/components/chat/ProviderContext";
import { SettingsProvider } from "@/components/settings/SettingsProvider";
import { User } from "@/lib/types";
import { ModalProvider } from "@/components/context/ModalContext";
import { AuthTypeMetadata } from "@/lib/userSS";
import { AppSidebarProvider } from "@/refresh-components/contexts/AppSidebarContext";
import { AgentsProvider } from "@/contexts/AgentsContext";

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
        <ProviderContextProvider>
          <AgentsProvider>
            <ModalProvider user={user}>
              <AppSidebarProvider folded={!!folded}>
                {children}
              </AppSidebarProvider>
            </ModalProvider>
          </AgentsProvider>
        </ProviderContextProvider>
      </UserProvider>
    </SettingsProvider>
  );
}
