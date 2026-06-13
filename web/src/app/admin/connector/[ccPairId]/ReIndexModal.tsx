"use client";

import { Button, Divider } from "@opal/components";
import { useState } from "react";
import { toast } from "@/hooks/useToast";
import { triggerIndexing } from "@/app/admin/connector/[ccPairId]/lib";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
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
            fromBeginning ? "完整重新索引" : "索引更新"
          }已成功启动`
        );
      } else {
        toast.error(result.message || "启动索引失败");
      }
    } catch (error) {
      console.error("触发索引失败：", error);
      toast.error(
        "尝试启动索引时发生意外错误"
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
          fromBeginning ? "完整重新索引" : "索引更新"
        }...`
      );

      // Then close the modal
      hide();

      // Then run the indexing operation
      await onRunIndex(fromBeginning);
    } catch (error) {
      console.error("启动索引出错：", error);
      // Show error in toast if needed
      toast.error("启动索引流程失败");
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <Modal open onOpenChange={hide}>
      <Modal.Content width="sm" height="sm">
        <Modal.Header icon={SvgRefreshCw} title="运行索引" onClose={hide} />
        <Modal.Body>
          <Text as="p">
            这会拉取并索引自上次成功索引以来发生变化或新增的所有文档。
          </Text>
          <Button disabled={isProcessing} onClick={() => handleRunIndex(false)}>
            运行更新
          </Button>

          <Divider />

          <Text as="p">
            这会对该来源中的所有文档执行完整重新索引。
          </Text>
          <Text as="p">
            <strong>注意：</strong>根据来源中存储的文档数量，此过程可能需要较长时间。
          </Text>

          <Button disabled={isProcessing} onClick={() => handleRunIndex(true)}>
            运行完整重新索引
          </Button>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
