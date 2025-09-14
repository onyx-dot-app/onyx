"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";

import { Button } from "@/components/ui/button";
import {
  CCPairFullInfo,
  ConnectorCredentialPairStatus,
  statusIsNotCurrentlyActive,
} from "./types";
import { usePopup } from "@/components/admin/connectors/Popup";
import { mutate } from "swr";
import { buildCCPairInfoUrl } from "./lib";
import { setCCPairStatus } from "@/lib/ccPair";
import { useState } from "react";
import { LoadingAnimation } from "@/components/Loading";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";

export function ModifyStatusButtonCluster({
  ccPair,
}: {
  ccPair: CCPairFullInfo;
}) {
  const { t } = useTranslation();
  const { popup, setPopup } = usePopup();
  const [isUpdating, setIsUpdating] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);

  const handleStatusChange = async (
    newStatus: ConnectorCredentialPairStatus
  ) => {
    if (isUpdating) return; // Prevent double-clicks or multiple requests

    if (
      ccPair.status === ConnectorCredentialPairStatus.INVALID &&
      newStatus === ConnectorCredentialPairStatus.ACTIVE
    ) {
      setShowConfirmModal(true);
    } else {
      await updateStatus(newStatus);
    }
  };

  const updateStatus = async (newStatus: ConnectorCredentialPairStatus) => {
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
  };

  // Compute the button text based on current state and backend status
  const isNotActive = statusIsNotCurrentlyActive(ccPair.status);
  const buttonText = isNotActive ? t(k.RE_ENABLE) : t(k.PAUSE);
  const tooltip = isNotActive
    ? t(k.CLICK_TO_START_INDEXING_AGAIN)
    : t(k.PAUSE_TOOLTIP_DESCRIPTION);

  return (
    <>
      {popup}
      <Button
        className="flex items-center justify-center w-auto min-w-[100px] px-4 py-2"
        variant={isNotActive ? "success-reverse" : "default"}
        disabled={isUpdating}
        onClick={() =>
          handleStatusChange(
            isNotActive
              ? ConnectorCredentialPairStatus.ACTIVE
              : ConnectorCredentialPairStatus.PAUSED
          )
        }
        tooltip={tooltip}
      >
        {isUpdating ? (
          <LoadingAnimation
            text={isNotActive ? t(k.RESUMING) : t(k.PAUSING)}
            size="text-md"
          />
        ) : (
          buttonText
        )}
      </Button>
      {showConfirmModal && (
        <ConfirmEntityModal
          entityType={t(k.INVALID_CONNECTOR)}
          entityName={ccPair.name}
          onClose={() => setShowConfirmModal(false)}
          onSubmit={() => {
            setShowConfirmModal(false);
            updateStatus(ConnectorCredentialPairStatus.ACTIVE);
          }}
          additionalDetails={t(k.INVALID_CONNECTOR_DETAILS)}
          actionButtonText={t(k.RE_ENABLE)}
          variant="action"
        />
      )}
    </>
  );
}
