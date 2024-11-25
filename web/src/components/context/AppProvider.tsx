import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { UserProvider } from "../user/UserProvider";
import { ProviderContextProvider } from "../chat_search/ProviderContext";
import { SettingsProvider } from "../settings/SettingsProvider";
import { AssistantsProvider } from "./AssistantsContext";
import { Persona } from "@/app/admin/assistants/interfaces";
import { User } from "@/lib/types";

interface AppProviderProps {
  children: React.ReactNode;
  user: User | null;
  settings: CombinedSettings;
  assistants: Persona[];
  hasAnyConnectors: boolean;
  hasImageCompatibleModel: boolean;
}

export const AppProvider = ({
  children,
  user,
  settings,
  assistants,
  hasAnyConnectors,
  hasImageCompatibleModel,
}: AppProviderProps) => {
  return (
    <UserProvider user={user}>
      <ProviderContextProvider>
        <SettingsProvider settings={settings}>
          <AssistantsProvider
            initialAssistants={assistants}
            hasAnyConnectors={hasAnyConnectors}
            hasImageCompatibleModel={hasImageCompatibleModel}
          >
            {children}
          </AssistantsProvider>
        </SettingsProvider>
      </ProviderContextProvider>
    </UserProvider>
  );
};
