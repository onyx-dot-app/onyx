"use client";
import i18n from "i18next";
import k from "./../../../../i18n/keys";

import { Button } from "@/components/ui/button";
import { CCPairFullInfo, ConnectorCredentialPairStatus } from "./types";
import { usePopup } from "@/components/admin/connectors/Popup";
import { FiTrash } from "react-icons/fi";
import { deleteCCPair } from "@/lib/documentDeletion";
import { mutate } from "swr";
import { buildCCPairInfoUrl } from "./lib";

export function DeletionButton({
  ccPair,
  refresh,
}: {
  ccPair: CCPairFullInfo;
  refresh: () => void;
}) {
  const { popup, setPopup } = usePopup();

  const isDeleting =
    ccPair?.latest_deletion_attempt?.status === "PENDING" ||
    ccPair?.latest_deletion_attempt?.status === "STARTED";

  let tooltip: string;
  if (ccPair.status !== ConnectorCredentialPairStatus.ACTIVE) {
    if (isDeleting) {
      tooltip = i18n.t(k.THIS_CONNECTOR_IS_CURRENTLY_BE);
    } else {
      tooltip = i18n.t(k.CLICK_TO_DELETE);
    }
  } else {
    tooltip = i18n.t(k.YOU_MUST_PAUSE_THE_CONNECTOR_B);
  }

  return (
    <div>
      {popup}
      <Button
        variant="destructive"
        onClick={async () => {
          try {
            // Await the delete operation to ensure it completes
            await deleteCCPair(
              ccPair.connector.id,
              ccPair.credential.id,
              setPopup,
              () => mutate(buildCCPairInfoUrl(ccPair.id))
            );

            // Call refresh to update the state after deletion
            refresh();
          } catch (error) {
            console.error("Error deleting connector:", error);
          }
        }}
        icon={FiTrash}
        disabled={
          ccPair.status === ConnectorCredentialPairStatus.ACTIVE || isDeleting
        }
        tooltip={tooltip}
      >
        {i18n.t(k.DELETE)}
      </Button>
    </div>
  );
}
