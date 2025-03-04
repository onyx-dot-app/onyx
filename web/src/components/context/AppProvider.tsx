"use client";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { UserProvider } from "../user/UserProvider";
import { ProviderContextProvider } from "../chat/ProviderContext";
import { SettingsProvider } from "../settings/SettingsProvider";
import { AssistantsProvider } from "./AssistantsContext";
import { Persona } from "@/app/admin/assistants/interfaces";
import { User } from "@/lib/types";
import { NewTeamModal } from "../modals/NewTeamModal";
import NewTenantModal from "../modals/NewTenantModal";

interface AppProviderProps {
  children: React.ReactNode;
  user: User | null;
  settings: CombinedSettings;
  assistants: Persona[];
  hasAnyConnectors: boolean;
  hasImageCompatibleModel: boolean;
}

//

export const AppProvider = ({
  children,
  user,
  settings,
  assistants,
  hasAnyConnectors,
  hasImageCompatibleModel,
}: AppProviderProps) => {
  // Render user-related modals based on conditionals
  const renderUserModals = () => {
    if (!user) return null;

    return (
      <>
        {/* Modal for users to request to join an existing team */}
        <NewTeamModal />

        {/* Modal for users who've been accepted to a new team */}
        {user.tenant_info?.new_tenant && (
          <NewTenantModal tenantInfo={user.tenant_info.new_tenant} />
        )}

        {/* Modal for users who've been invited to join a team */}
        {user.tenant_info?.invitation && (
          <NewTenantModal
            isInvite={true}
            tenantInfo={user.tenant_info.invitation}
          />
        )}
      </>
    );
  };

  return (
    <SettingsProvider settings={settings}>
      <UserProvider settings={settings} user={user}>
        <ProviderContextProvider>
          <AssistantsProvider
            initialAssistants={assistants}
            hasAnyConnectors={hasAnyConnectors}
            hasImageCompatibleModel={hasImageCompatibleModel}
          >
            {/* Main application content */}
            {children}

            {/* User-related modals */}
            {renderUserModals()}
          </AssistantsProvider>
        </ProviderContextProvider>
      </UserProvider>
    </SettingsProvider>
  );
};
