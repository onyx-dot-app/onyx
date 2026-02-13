"use client";

import Button from "@/refresh-components/buttons/Button";
import { useState } from "react";
import { toast } from "@/hooks/useToast";
import { triggerIndexing } from "@/app/admin/connector/[ccPairId]/lib";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import Separator from "@/refresh-components/Separator";
import { SvgRefreshCw } from "@opal/icons";
// Hook to handle re-indexing functionality
export function useReIndexModal(
  connectorId: number | null,
  credentialId: number | null,
  ccPairId: number | null
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
        ccPairId
      );

      // Show appropriate notification based on result
      if (result.success) {
        toast.success(
          `${
            fromBeginning ? "Complete re-indexing" : "Indexing update"
          } started successfully`
        );
      } else {
        toast.error(result.message || "Failed to start indexing");
      }
    } catch (error) {
      console.error("Failed to trigger indexing:", error);
      toast.error(
        "An unexpected error occurred while trying to start indexing"
      );
    }
  };

  const FinalReIndexModal =
    reIndexPopupVisible &&
    connectorId != null &&
    credentialId != null &&
    ccPairId != null ? (
      <ReIndexModal hide={hideReIndexModal} onRunIndex={triggerReIndex} />
    ) : null;

  return {
    showReIndexModal,
    ReIndexModal: FinalReIndexModal,
  };
}

export interface ReIndexModalProps {
  hide: () => void;
  onRunIndex: (fromBeginning: boolean) => Promise<void>;
}

export default function ReIndexModal({ hide, onRunIndex }: ReIndexModalProps) {
  const [isProcessing, setIsProcessing] = useState(false);

  const handleRunIndex = async (fromBeginning: boolean) => {
    if (isProcessing) return;

    setIsProcessing(true);
    try {
      // First show immediate feedback with a toast
      toast.info(
        `Starting ${
          fromBeginning ? "complete re-indexing" : "indexing update"
        }...`
      );

      // Then close the modal
      hide();

      // Then run the indexing operation
      await onRunIndex(fromBeginning);
    } catch (error) {
      console.error("Error starting indexing:", error);
      // Show error in toast if needed
      toast.error("Failed to start indexing process");
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <Modal open onOpenChange={hide}>
      <Modal.Content width="sm" height="sm">
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
