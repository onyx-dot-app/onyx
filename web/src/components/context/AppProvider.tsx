"use client";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { UserProvider } from "../user/UserProvider";
import { ProviderContextProvider } from "../chat/ProviderContext";
import { SettingsProvider } from "../settings/SettingsProvider";
import { AssistantsProvider } from "./AssistantsContext";
import { Persona } from "@/app/admin/assistants/interfaces";
import { User } from "@/lib/types";
import { NewOrganizationModal } from "../modals/NewOrganizationModal";
import NewTenantModal from "./NewTenantModal";

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
  return (
    <SettingsProvider settings={settings}>
      <UserProvider settings={settings} user={user}>
        <ProviderContextProvider>
          <AssistantsProvider
            initialAssistants={assistants}
            hasAnyConnectors={hasAnyConnectors}
            hasImageCompatibleModel={hasImageCompatibleModel}
          >
            {children}

            {user && <NewOrganizationModal />}

            {user?.tenant_info?.new_tenant && (
              <NewTenantModal tenantInfo={user.tenant_info.new_tenant} />
            )}
            {user?.tenant_info?.invitation && (
              <NewTenantModal
                isInvite
                tenantInfo={user.tenant_info.invitation}
              />
            )}
          </AssistantsProvider>
        </ProviderContextProvider>
      </UserProvider>
    </SettingsProvider>
  );
};
