"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import NewTeamModal from "@/components/modals/NewTeamModal";
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
  const [newTenantInfo, setNewTenantInfo] = useState<NewTenantInfo | null>(
    null
  );
  const [invitationInfo, setInvitationInfo] = useState<NewTenantInfo | null>(
    null
  );

  // Sync modal states with user info — clear when backend no longer has the data
  useEffect(() => {
    if (user?.tenant_info?.new_tenant) {
      setNewTenantInfo(user.tenant_info.new_tenant);
    } else {
      setNewTenantInfo(null);
    }
    if (user?.tenant_info?.invitation) {
      setInvitationInfo(user.tenant_info.invitation);
    } else {
      setInvitationInfo(null);
    }
  }, [user?.tenant_info]);

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
