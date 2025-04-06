"use client";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { UserProvider } from "../user/UserProvider";
import { ProviderContextProvider } from "../chat/ProviderContext";
import { SettingsProvider } from "../settings/SettingsProvider";
import { AssistantsProvider } from "./AssistantsContext";
import { Persona } from "@/app/admin/assistants/interfaces";
import { User } from "@/lib/types";
import { ModalProvider } from "./ModalContext";
import { DemoModeProvider } from "../demo/DemoModeContext";

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
    <SettingsProvider settings={settings}>
      <UserProvider settings={settings} user={user}>
        <ProviderContextProvider>
          <AssistantsProvider
            initialAssistants={assistants}
            hasAnyConnectors={hasAnyConnectors}
            hasImageCompatibleModel={hasImageCompatibleModel}
          >
            <DemoModeProvider>
              <ModalProvider user={user}>{children}</ModalProvider>
            </DemoModeProvider>
          </AssistantsProvider>
        </ProviderContextProvider>
      </UserProvider>
    </SettingsProvider>
  );
};
