"use client";

import { Button } from "@/components/ui/button";
import { CCPairFullInfo, ConnectorCredentialPairStatus } from "./types";
import { usePopup } from "@/components/admin/connectors/Popup";
import { mutate } from "swr";
import { buildCCPairInfoUrl } from "./lib";
import { setCCPairStatus } from "@/lib/ccPair";
import { useState } from "react";
import { LoadingAnimation } from "@/components/Loading";

export function ModifyStatusButtonCluster({
  ccPair,
}: {
  ccPair: CCPairFullInfo;
}) {
  const { popup, setPopup } = usePopup();
  const [isUpdating, setIsUpdating] = useState(false);

  const handleStatusChange = async (
    newStatus: ConnectorCredentialPairStatus
  ) => {
    if (isUpdating) return; // Prevent double-clicks or multiple requests
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
  const buttonText =
    ccPair.status === ConnectorCredentialPairStatus.PAUSED
      ? "Re-Enable"
      : "Pause";

  const tooltip =
    ccPair.status === ConnectorCredentialPairStatus.PAUSED
      ? "Click to start indexing again!"
      : "When paused, the connector's documents will still be visible. However, no new documents will be indexed.";

  return (
    <>
      {popup}
      <Button
        className="flex items-center justify-center w-auto min-w-[100px] px-4 py-2"
        variant={
          ccPair.status === ConnectorCredentialPairStatus.PAUSED
            ? "success-reverse"
            : "default"
        }
        disabled={isUpdating}
        onClick={() =>
          handleStatusChange(
            ccPair.status === ConnectorCredentialPairStatus.PAUSED
              ? ConnectorCredentialPairStatus.ACTIVE
              : ConnectorCredentialPairStatus.PAUSED
          )
        }
        tooltip={tooltip}
      >
        {isUpdating ? (
          <LoadingAnimation
            text={
              ccPair.status === ConnectorCredentialPairStatus.PAUSED
                ? "Resuming"
                : "Pausing"
            }
            size="text-md"
          />
        ) : (
          buttonText
        )}
      </Button>
    </>
  );
}
