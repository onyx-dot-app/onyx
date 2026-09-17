"use client";

import { Button, Divider } from "@opal/components";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "@opal/layouts";
import { triggerIndexing } from "@/app/admin/connector/[ccPairId]/lib";
import { Modal } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { SvgRefreshCw } from "@opal/icons";
// Hook to handle re-indexing functionality
export function useReIndexModal(
  connectorId: number | null,
  credentialId: number | null,
  ccPairId: number | null
) {
  const t = useTranslations("admin.connector");
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
          fromBeginning
            ? t("toasts.completeReindexStarted")
            : t("toasts.indexingUpdateStarted")
        );
      } else {
        toast.error(result.message || t("toasts.indexingStartFailed"));
      }
    } catch (error) {
      console.error("Failed to trigger indexing:", error);
      toast.error(t("toasts.indexingStartUnexpectedError"));
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
  const t = useTranslations("admin.connector");
  const [isProcessing, setIsProcessing] = useState(false);

  const handleRunIndex = async (fromBeginning: boolean) => {
    if (isProcessing) return;

    setIsProcessing(true);
    try {
      // First show immediate feedback with a toast
      toast.info(
        fromBeginning
          ? t("toasts.completeReindexStarting")
          : t("toasts.indexingUpdateStarting")
      );

      // Then close the modal
      hide();

      // Then run the indexing operation
      await onRunIndex(fromBeginning);
    } catch (error) {
      console.error("Error starting indexing:", error);
      // Show error in toast if needed
      toast.error(t("toasts.indexingProcessStartFailed"));
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <Modal open onOpenChange={hide}>
      <Modal.Content width="sm" height="sm">
        <Modal.Header
          icon={SvgRefreshCw}
          title={t("reIndexModal.title")}
          onClose={hide}
        />
        <Modal.Body>
          <Text as="p">{t("reIndexModal.update.description")}</Text>
          <Button disabled={isProcessing} onClick={() => handleRunIndex(false)}>
            {t("reIndexModal.updateButton.label")}
          </Button>

          <Divider />

          <Text as="p">{t("reIndexModal.fullReindex.description")}</Text>
          <Text as="p">
            {t.rich("reIndexModal.fullReindex.note", {
              strong: (chunks) => <strong>{chunks}</strong>,
            })}
          </Text>

          <Button disabled={isProcessing} onClick={() => handleRunIndex(true)}>
            {t("reIndexModal.fullReindexButton.label")}
          </Button>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
