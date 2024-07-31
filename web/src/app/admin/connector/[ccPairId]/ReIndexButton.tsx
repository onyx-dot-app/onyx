"use client";

import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { runConnector } from "@/lib/connector";
import { Button, Divider, Text } from "@tremor/react";
import { mutate } from "swr";
import { buildCCPairInfoUrl } from "./lib";
import { useState } from "react";
import { Modal } from "@/components/Modal";

function ReIndexPopup({
  connectorId,
  credentialId,
  ccPairId,
  setPopup,
  hide,
}: {
  connectorId: number;
  credentialId: number;
  ccPairId: number;
  setPopup: (popupSpec: PopupSpec | null) => void;
  hide: () => void;
}) {
  async function triggerIndexing(fromBeginning: boolean) {
    const errorMsg = await runConnector(
      connectorId,
      [credentialId],
      fromBeginning
    );
    if (errorMsg) {
      setPopup({
        message: errorMsg,
        type: "error",
      });
    } else {
      setPopup({
        message: "Triggered connector run",
        type: "success",
      });
    }
    mutate(buildCCPairInfoUrl(ccPairId));
  }

  return (
    <Modal title="Run Indexing" onOutsideClick={hide}>
      <div>
        <Button
          className="ml-auto"
          color="green"
          size="xs"
          onClick={() => {
            triggerIndexing(false);
            hide();
          }}
        >
          Run Update
        </Button>

        <Text className="mt-2">
          This will pull in and index all documents that have changed and/or
          have been added since the last successful indexing run.
        </Text>

        <Divider />

        <Button
          className="ml-auto"
          color="green"
          size="xs"
          onClick={() => {
            triggerIndexing(true);
            hide();
          }}
        >
          Run Complete Re-Indexing
        </Button>

        <Text className="mt-2">
          This will cause a complete re-indexing of all documents from the
          source.
        </Text>

        <Text className="mt-2">
          <b>NOTE:</b> depending on the number of documents stored in the
          source, this may take a long time.
        </Text>
      </div>
    </Modal>
  );
}

export function ReIndexButton({
  ccPairId,
  connectorId,
  credentialId,
  isDisabled,
  isDeleting,
}: {
  ccPairId: number;
  connectorId: number;
  credentialId: number;
  isDisabled: boolean;
  isDeleting: boolean;
}) {
  const { popup, setPopup } = usePopup();
  const [reIndexPopupVisible, setReIndexPopupVisible] = useState(false);

  return (
    <>
      {reIndexPopupVisible && (
        <ReIndexPopup
          connectorId={connectorId}
          credentialId={credentialId}
          ccPairId={ccPairId}
          setPopup={setPopup}
          hide={() => setReIndexPopupVisible(false)}
        />
      )}
      {popup}
      <Button
        className="ml-auto"
        color="green"
        size="xs"
        onClick={() => {
          setReIndexPopupVisible(true);
        }}
        disabled={isDisabled || isDeleting}
        tooltip={
          isDeleting
            ? "Cannot index while connector is deleting"
            : isDisabled
              ? "Connector must be re-enabled before indexing"
              : undefined
        }
      >
        Index
      </Button>
    </>
  );
}
