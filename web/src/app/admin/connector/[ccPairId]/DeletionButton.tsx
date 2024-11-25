"use client";

import { Button } from "@/components/ui/button";
import { CCPairFullInfo, ConnectorCredentialPairStatus } from "./types";
import { usePopup } from "@/components/admin/connectors/Popup";
import { FiTrash } from "react-icons/fi";
import { deleteCCPair } from "@/lib/documentDeletion";
import { mutate } from "swr";
import { buildCCPairInfoUrl } from "./lib";

export function DeletionButton({ ccPair }: { ccPair: CCPairFullInfo }) {
  const { popup, setPopup } = usePopup();

  const isDeleting =
    ccPair?.latest_deletion_attempt?.status === "PENDING" ||
    ccPair?.latest_deletion_attempt?.status === "STARTED";

  let tooltip: string;
  if (ccPair.status !== ConnectorCredentialPairStatus.ACTIVE) {
    if (isDeleting) {
      tooltip = "This connector is currently being deleted";
    } else {
      tooltip = "Click to delete";
    }
  } else {
    tooltip = "You must pause the connector before deleting it";
  }

  return (
    <div>
      {popup}
      <Button
        variant="destructive"
        onClick={() =>
          deleteCCPair(
            ccPair.connector.id,
            ccPair.credential.id,
            setPopup,
            () => mutate(buildCCPairInfoUrl(ccPair.id))
          )
        }
        icon={FiTrash}

        disabled={
          ccPair.status === ConnectorCredentialPairStatus.ACTIVE
        }
        tooltip={tooltip}
      >
        Delete
      </Button>
    </div>
  );
}
