import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { UserProvider } from "../user/UserProvider";
import { ProviderContextProvider } from "../chat_search/ProviderContext";
import { SettingsProvider } from "../settings/SettingsProvider";
import { AssistantsProvider } from "./AssistantsContext";
import { Persona } from "@/app/admin/assistants/interfaces";
import { User } from "@/lib/types";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { ChatProvider } from "./ChatContext";
import { redirect } from "next/navigation";

interface AppProviderProps {
  children: React.ReactNode;
  user: User | null;
  settings: CombinedSettings;
  assistants: Persona[];
  hasAnyConnectors: boolean;
  hasImageCompatibleModel: boolean;
  data: any;
}

export const AppProvider = ({
  children,
  user,
  settings,
  assistants,
  hasAnyConnectors,
  hasImageCompatibleModel,
  data,
}: AppProviderProps) => {
  const {
    chatSessions,
    availableSources,
    documentSets,
    tags,
    llmProviders,
    folders,
    openedFolders,
    toggleSidebar,
    defaultAssistantId,
    shouldShowWelcomeModal,
    ccPairs,
    inputPrompts,
  } = data;

  return (
    <UserProvider user={user}>
      <ProviderContextProvider>
        <SettingsProvider settings={settings}>
          <ChatProvider
            value={{
              inputPrompts,
              chatSessions,
              toggledSidebar: toggleSidebar,
              availableSources,
              ccPairs,
              documentSets,
              tags,
              availableDocumentSets: documentSets,
              availableTags: tags,
              llmProviders,
              folders,
              openedFolders,
              shouldShowWelcomeModal,
              defaultAssistantId,
            }}
          >
            <AssistantsProvider
              initialAssistants={assistants}
              hasAnyConnectors={hasAnyConnectors}
              hasImageCompatibleModel={hasImageCompatibleModel}
            >
              {children}
            </AssistantsProvider>
          </ChatProvider>
        </SettingsProvider>
      </ProviderContextProvider>
    </UserProvider>
  );
};
