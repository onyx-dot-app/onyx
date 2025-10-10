"use client";

import { Button } from "@/components/ui/button";
import { useState } from "react";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { triggerIndexing } from "./lib";
import { Modal } from "@/components/Modal";
import Text from "@/components/ui/text";
import { Separator } from "@/components/ui/separator";

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

interface ReIndexModalProps {
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
    <Modal title="Run Indexing" onOutsideClick={hide}>
      <div>
        <Button
          variant="submit"
          className="ml-auto"
          onClick={() => handleRunIndex(false)}
          disabled={isProcessing}
        >
          Run Update
        </Button>

        <Text className="mt-2">
          This will pull in and index all documents that have changed and/or
          have been added since the last successful indexing run.
        </Text>

        <Separator />

        <Button
          variant="submit"
          className="ml-auto"
          onClick={() => handleRunIndex(true)}
          disabled={isProcessing}
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
