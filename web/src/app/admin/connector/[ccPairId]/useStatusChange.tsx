"use client";

import { CCPairFullInfo, ConnectorCredentialPairStatus } from "./types";
import { usePopup } from "@/components/admin/connectors/Popup";
import { mutate } from "swr";
import { buildCCPairInfoUrl } from "./lib";
import { setCCPairStatus } from "@/lib/ccPair";
import { useState } from "react";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import { useModalProvider } from "@/refresh-components/contexts/ModalContext";

// Export the status change functionality separately
export default function useStatusChange(ccPair: CCPairFullInfo | null) {
  const { setPopup } = usePopup();
  const [isUpdating, setIsUpdating] = useState(false);
  const confirmModal = useModalProvider();

  const updateStatus = async (newStatus: ConnectorCredentialPairStatus) => {
    if (!ccPair) return false;

    setIsUpdating(true);

    try {
      // Call the backend to update the status
      await setCCPairStatus(ccPair.id, newStatus, setPopup);

      // Use mutate to revalidate the status on the backend
      await mutate(buildCCPairInfoUrl(ccPair.id));
    } catch (error) {
      console.error("Failed to update status", error);
    } finally {
      // Reset local updating state and button text after mutation
      setIsUpdating(false);
    }

    return true;
  };

  const handleStatusChange = async (
    newStatus: ConnectorCredentialPairStatus
  ) => {
    if (isUpdating || !ccPair) return false; // Prevent double-clicks or multiple requests

    if (
      ccPair.status === ConnectorCredentialPairStatus.INVALID &&
      newStatus === ConnectorCredentialPairStatus.ACTIVE
    ) {
      confirmModal.toggle(true);
      return false;
    } else {
      return await updateStatus(newStatus);
    }
  };

  const ConfirmModal = (
    <confirmModal.Provider>
      {ccPair && (
        <ConfirmEntityModal
          entityType="Invalid Connector"
          entityName={ccPair.name}
          onClose={() => confirmModal.toggle(false)}
          onSubmit={() => {
            confirmModal.toggle(false);
            updateStatus(ConnectorCredentialPairStatus.ACTIVE);
          }}
          additionalDetails="This connector was previously marked as invalid. Please verify that your configuration is correct before re-enabling. Are you sure you want to proceed?"
          actionButtonText="Re-Enable"
        />
      )}
    </confirmModal.Provider>
  );

  return {
    handleStatusChange,
    isUpdating,
    ConfirmModal,
  };
}
