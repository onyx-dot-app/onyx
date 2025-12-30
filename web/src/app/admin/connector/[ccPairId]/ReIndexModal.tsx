"use client";

import Button from "@/refresh-components/buttons/Button";
import { useState } from "react";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { triggerIndexing } from "@/app/admin/connector/[ccPairId]/lib";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import Separator from "@/refresh-components/Separator";
import { SvgRefreshCw } from "@opal/icons";
// Hook to handle re-indexing functionality
export function useReIndexModal(
  connectorId: number | null,
  credentialId: number | null,
  ccPairId: number | null,
  setPopup: (popupSpec: PopupSpec | null) => void
) {
  const [reIndexPopupVisible, setReIndexPopupVisible] = useState(false);

  const showReIndexModal = () => {
    if (connectorId == null || credentialId == null || ccPairId == null) {
      return;
    }
    setReIndexPopupVisible(true);
  };

  const hideReIndexModal = () => {
    setReIndexPopupVisible(false);
  };

  const triggerReIndex = async (fromBeginning: boolean) => {
    if (connectorId == null || credentialId == null || ccPairId == null) {
      return;
    }

    try {
      const result = await triggerIndexing(
        fromBeginning,
        connectorId,
        credentialId,
        ccPairId,
        setPopup
      );

      // Show appropriate notification based on result
      if (result.success) {
        setPopup({
          message: `${
            fromBeginning ? "Complete re-indexing" : "Indexing update"
          } started successfully`,
          type: "success",
        });
      } else {
        setPopup({
          message: result.message || "Failed to start indexing",
          type: "error",
        });
      }
    } catch (error) {
      console.error("Failed to trigger indexing:", error);
      setPopup({
        message: "An unexpected error occurred while trying to start indexing",
        type: "error",
      });
    }
  };

  const FinalReIndexModal =
    reIndexPopupVisible &&
    connectorId != null &&
    credentialId != null &&
    ccPairId != null ? (
      <ReIndexModal
        setPopup={setPopup}
        hide={hideReIndexModal}
        onRunIndex={triggerReIndex}
      />
    ) : null;

  return {
    showReIndexModal,
    ReIndexModal: FinalReIndexModal,
  };
}

export interface ReIndexModalProps {
  setPopup: (popupSpec: PopupSpec | null) => void;
  hide: () => void;
  onRunIndex: (fromBeginning: boolean) => Promise<void>;
}

export default function ReIndexModal({
  setPopup,
  hide,
  onRunIndex,
}: ReIndexModalProps) {
  const [isProcessing, setIsProcessing] = useState(false);

  const handleRunIndex = async (fromBeginning: boolean) => {
    if (isProcessing) return;

    setIsProcessing(true);
    try {
      // First show immediate feedback with a popup
      setPopup({
        message: `Starting ${
          fromBeginning ? "complete re-indexing" : "indexing update"
        }...`,
        type: "info",
      });

      // Then close the modal
      hide();

      // Then run the indexing operation
      await onRunIndex(fromBeginning);
    } catch (error) {
      console.error("Error starting indexing:", error);
      // Show error in popup if needed
      setPopup({
        message: "Failed to start indexing process",
        type: "error",
      });
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <Modal open onOpenChange={hide}>
      <Modal.Content small>
        <Modal.Header icon={SvgRefreshCw} title="Run Indexing" onClose={hide} />
        <Modal.Body>
          <Text as="p">
            This will pull in and index all documents that have changed and/or
            have been added since the last successful indexing run.
          </Text>
          <Button onClick={() => handleRunIndex(false)} disabled={isProcessing}>
            Run Update
          </Button>

          <Separator />

          <Text as="p">
            This will cause a complete re-indexing of all documents from the
            source.
          </Text>
          <Text as="p">
            <strong>NOTE:</strong> depending on the number of documents stored
            in the source, this may take a long time.
          </Text>

          <Button onClick={() => handleRunIndex(true)} disabled={isProcessing}>
            Run Complete Re-Indexing
          </Button>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
