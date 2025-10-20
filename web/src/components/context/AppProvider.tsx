"use client";

import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { UserProvider } from "@/components/user/UserProvider";
import { ProviderContextProvider } from "@/components/chat/ProviderContext";
import { SettingsProvider } from "@/components/settings/SettingsProvider";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { User } from "@/lib/types";
import { ModalProvider } from "@/components/context/ModalContext";
import { AuthTypeMetadata } from "@/lib/userSS";
import { AgentsProvider } from "@/refresh-components/contexts/AgentsContext";
import { AppSidebarProvider } from "@/refresh-components/contexts/AppSidebarContext";

interface AppProviderProps {
  children: React.ReactNode;
  user: User | null;
  settings: CombinedSettings;
  assistants: MinimalPersonaSnapshot[];
  authTypeMetadata: AuthTypeMetadata;
  folded?: boolean;
}

export default function AppProvider({
  children,
  user,
  settings,
  assistants,
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
          <ModalProvider user={user}>
            <AgentsProvider
              agents={assistants}
              pinnedAgentIds={user?.preferences.pinned_assistants || []}
            >
              <AppSidebarProvider folded={!!folded}>
                {children}
              </AppSidebarProvider>
            </AgentsProvider>
          </ModalProvider>
        </ProviderContextProvider>
      </UserProvider>
    </SettingsProvider>
  );
}
