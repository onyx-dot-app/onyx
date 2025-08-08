"use client";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { UserProvider } from "../user/UserProvider";
import { ProviderContextProvider } from "../chat/ProviderContext";
import { SettingsProvider } from "../settings/SettingsProvider";
import { AssistantsProvider } from "./AssistantsContext";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { User } from "@/lib/types";
import { ModalProvider } from "./ModalContext";
import { AuthTypeMetadata } from "@/lib/userSS";

interface AppProviderProps {
  children: React.ReactNode;
  user: User | null;
  settings: CombinedSettings;
  assistants: MinimalPersonaSnapshot[];
  authTypeMetadata: AuthTypeMetadata;
}

export const AppProvider = ({
  children,
  user,
  settings,
  assistants,
  authTypeMetadata,
}: AppProviderProps) => {
  return (
    <SettingsProvider settings={settings}>
      <UserProvider
        settings={settings}
        user={user}
        authTypeMetadata={authTypeMetadata}
      >
        <ProviderContextProvider>
          <AssistantsProvider initialAssistants={assistants}>
            <ModalProvider user={user}>{children}</ModalProvider>
          </AssistantsProvider>
        </ProviderContextProvider>
      </UserProvider>
    </SettingsProvider>
  );
};
