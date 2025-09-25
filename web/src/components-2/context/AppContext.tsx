import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { UserProvider } from "@/components/user/UserProvider";
import { ProviderContextProvider } from "@/components/chat/ProviderContext";
import { SettingsProvider } from "@/components/settings/SettingsProvider";
import { AssistantsProvider } from "@/components/context/AssistantsContext";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { User } from "@/lib/types";
import { ModalProvider } from "@/components/context/ModalContext";
import { ModalProvider as NewModalProvider } from "@/components-2/context/ModalContext";
import { AuthTypeMetadata } from "@/lib/userSS";
import { AgentsProvider } from "@/components-2/context/AgentsContext";

interface AppProviderProps {
  children: React.ReactNode;
  user: User | null;
  settings: CombinedSettings;
  agents: MinimalPersonaSnapshot[];
  authTypeMetadata: AuthTypeMetadata;
}

export function AppProvider({
  children,
  user,
  settings,
  agents,
  authTypeMetadata,
}: AppProviderProps) {
  return (
    <SettingsProvider settings={settings}>
      <UserProvider
        settings={settings}
        user={user}
        authTypeMetadata={authTypeMetadata}
      >
        <ProviderContextProvider>
          <AssistantsProvider initialAssistants={agents}>
            <ModalProvider user={user}>
              <AgentsProvider
                agents={agents}
                pinnedAgentIds={user?.preferences.pinned_assistants || []}
              >
                <NewModalProvider>{children}</NewModalProvider>
              </AgentsProvider>
            </ModalProvider>
          </AssistantsProvider>
        </ProviderContextProvider>
      </UserProvider>
    </SettingsProvider>
  );
}
