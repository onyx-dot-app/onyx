"use client";

import { PopupSpec } from "@/components/admin/connectors/Popup";
import { Button } from "@/components/ui/button";
import Text from "@/components/ui/text";
import { Modal } from "@/components/Modal";
import { Separator } from "@/components/ui/separator";
import { useState } from "react";

interface ReIndexPopupProps {
  connectorId: number;
  credentialId: number;
  ccPairId: number;
  setPopup: (popupSpec: PopupSpec | null) => void;
  hide: () => void;
  onRunIndex: (fromBeginning: boolean) => Promise<void>;
}

export default function ReIndexPopup({
  connectorId,
  credentialId,
  ccPairId,
  setPopup,
  hide,
  onRunIndex,
}: ReIndexPopupProps) {
  const [isProcessing, setIsProcessing] = useState(false);

  const handleRunIndex = async (fromBeginning: boolean) => {
    if (isProcessing) return;

    setIsProcessing(true);
    try {
      // First close the modal to give immediate feedback
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
