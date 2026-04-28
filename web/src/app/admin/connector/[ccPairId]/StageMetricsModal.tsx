"use client";

import Modal from "@/refresh-components/Modal";
import { SvgBarChartSmall } from "@opal/icons";
import StageMetricsPanel from "./stage-metrics/StageMetricsPanel";

interface StageMetricsModalProps {
  indexAttemptId: number;
  onClose: () => void;
}

export default function StageMetricsModal({
  indexAttemptId,
  onClose,
}: StageMetricsModalProps) {
  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          icon={SvgBarChartSmall}
          title="Indexing stage metrics"
          description="Per-batch and per-attempt timing for this index attempt."
          onClose={onClose}
        />
        <Modal.Body>
          <StageMetricsPanel indexAttemptId={indexAttemptId} />
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
