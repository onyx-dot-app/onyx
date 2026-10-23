"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { BasicModalFooter, Button, Modal } from "@opal/components";
import { SvgAlertTriangle, SvgListTree } from "@opal/icons";
import { markdown } from "@opal/utils";

export interface FailedChecksAdvisoryModalProps {
  /** How many non-required checks failed. Create does not wait on them. */
  failedCount: number;
  /** Create is still possible. Once it is not, the modal closes itself. */
  canCreate: boolean;
  onClose: () => void;
  /** Closes the modal and shows the checks card. */
  onViewChecks: () => void;
  /** Closes the modal and creates the connector regardless. */
  onProceed: () => void;
}

/** Warns before Create that content under a failed non-required check stays out of the index. */
export default function FailedChecksAdvisoryModal({
  failedCount,
  canCreate,
  onClose,
  onViewChecks,
  onProceed,
}: FailedChecksAdvisoryModalProps) {
  const t = useTranslations("admin.connectorChecks.advisory");
  // A refresh can drop the picked account while the modal is open.
  useEffect(() => {
    if (!canCreate) onClose();
  }, [canCreate, onClose]);
  return (
    <Modal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgAlertTriangle}
          color="warning"
          title={t("title")}
          description={markdown(
            t("description", { count: failedCount }),
            "",
            t("proceed")
          )}
          onClose={onClose}
        />
        <Modal.Footer>
          <BasicModalFooter
            left={
              <Button
                prominence="secondary"
                icon={SvgListTree}
                onClick={onViewChecks}
              >
                {t("viewButton.label")}
              </Button>
            }
            submit={
              <Button onClick={onProceed}>{t("proceedButton.label")}</Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
