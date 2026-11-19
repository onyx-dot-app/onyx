"use client";

import React, { createContext, useContext, useState } from "react";
import NewTeamModal from "@/sections/modals/NewTeamModal";
import NewTenantModal from "@/sections/modals/NewTenantModal";
import { NewTenantInfo } from "@/lib/types";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useUser } from "@/providers/UserProvider";

type ModalContextType = {
  showNewTeamModal: boolean;
  setShowNewTeamModal: (show: boolean) => void;
  newTenantInfo: NewTenantInfo | null;
  setNewTenantInfo: (info: NewTenantInfo | null) => void;
  invitationInfo: NewTenantInfo | null;
  setInvitationInfo: (info: NewTenantInfo | null) => void;
};

const ModalContext = createContext<ModalContextType | undefined>(undefined);

export const useModalContext = () => {
  const context = useContext(ModalContext);
  if (context === undefined) {
    throw new Error("useModalContext must be used within a ModalProvider");
  }
  return context;
};

export const ModalProvider: React.FC<{
  children: React.ReactNode;
}> = ({ children }) => {
  const { user } = useUser();
  const [showNewTeamModal, setShowNewTeamModal] = useState(false);
  const tenantInfo = user?.tenant_info;
  const [newTenantInfo, setNewTenantInfo] = useState<NewTenantInfo | null>(
    tenantInfo?.new_tenant || null
  );
  const [invitationInfo, setInvitationInfo] = useState<NewTenantInfo | null>(
    tenantInfo?.invitation || null
  );

  // Follow the user's tenant info, and clear when the backend no longer has it.
  const [syncedTenantInfo, setSyncedTenantInfo] = useState(tenantInfo);
  if (syncedTenantInfo !== tenantInfo) {
    setSyncedTenantInfo(tenantInfo);
    setNewTenantInfo(tenantInfo?.new_tenant || null);
    setInvitationInfo(tenantInfo?.invitation || null);
  }

  // Render all application-wide modals
  const renderModals = () => {
    if (!user || !NEXT_PUBLIC_CLOUD_ENABLED) return <></>;

    return (
      <>
        {/* Modal for users to request to join an existing team */}
        <NewTeamModal />

        {/* Modal for users who've been accepted to a new team */}
        {newTenantInfo && (
          <NewTenantModal
            tenantInfo={newTenantInfo}
            // Close function to clear the modal state
            onClose={() => setNewTenantInfo(null)}
          />
        )}

        {/* Modal for users who've been invited to join a team */}
        {invitationInfo && (
          <NewTenantModal
            isInvite={true}
            tenantInfo={invitationInfo}
            // Close function to clear the modal state
            onClose={() => setInvitationInfo(null)}
          />
        )}
      </>
    );
  };

  return (
    <ModalContext.Provider
      value={{
        showNewTeamModal,
        setShowNewTeamModal,
        newTenantInfo,
        setNewTenantInfo,
        invitationInfo,
        setInvitationInfo,
      }}
    >
      {children}
      {renderModals()}
    </ModalContext.Provider>
  );
};
