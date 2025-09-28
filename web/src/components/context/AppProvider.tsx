"use client";

import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { UserProvider } from "../user/UserProvider";
import { ProviderContextProvider } from "../chat/ProviderContext";
import { SettingsProvider } from "../settings/SettingsProvider";
import { AssistantsProvider } from "./AssistantsContext";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { User } from "@/lib/types";
import { ModalProvider } from "./ModalContext";
import { ModalProvider as NewModalProvider } from "@/components-2/context/ModalContext";
import { AuthTypeMetadata } from "@/lib/userSS";
import { AgentsProvider } from "@/components-2/context/AgentsContext";
import { AppSidebarProvider } from "@/components-2/context/AppSidebarContext";

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
          <AssistantsProvider initialAssistants={assistants}>
            <ModalProvider user={user}>
              <AgentsProvider
                agents={assistants}
                pinnedAgentIds={user?.preferences.pinned_assistants || []}
              >
                <NewModalProvider>
                  <AppSidebarProvider folded={!!folded}>
                    {children}
                  </AppSidebarProvider>
                </NewModalProvider>
              </AgentsProvider>
            </ModalProvider>
          </AssistantsProvider>
        </ProviderContextProvider>
      </UserProvider>
    </SettingsProvider>
  );
}
