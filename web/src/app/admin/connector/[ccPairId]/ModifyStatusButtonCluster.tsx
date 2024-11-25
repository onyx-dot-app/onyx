"use client";

import { Button } from "@/components/ui/button";
import { CCPairFullInfo, ConnectorCredentialPairStatus } from "./types";
import { usePopup } from "@/components/admin/connectors/Popup";
import { mutate } from "swr";
import { buildCCPairInfoUrl } from "./lib";
import { setCCPairStatus } from "@/lib/ccPair";

export function ModifyStatusButtonCluster({
  ccPair,
}: {
  ccPair: CCPairFullInfo;
}) {
  const { popup, setPopup } = usePopup();

  return (
    <>
      {popup}
      {ccPair.status === ConnectorCredentialPairStatus.PAUSED ? (
        <Button
          variant="success-reverse"
          onClick={() =>
            setCCPairStatus(
              ccPair.id,
              ConnectorCredentialPairStatus.ACTIVE,
              setPopup,
              () => mutate(buildCCPairInfoUrl(ccPair.id))
            )
          }
          tooltip="Click to start indexing again!"
        >
          Re-Enable
        </Button>
      ) : (
        <Button
          variant="default"
          onClick={() =>
            setCCPairStatus(
              ccPair.id,
              ConnectorCredentialPairStatus.PAUSED,
              setPopup,
              () => mutate(buildCCPairInfoUrl(ccPair.id))
            )
          }
          tooltip={
            "When paused, the connectors documents will still" +
            " be visible. However, no new documents will be indexed."
          }
        >
          Pause
        </Button>
      )}
    </>
  );
}
