"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { BasicModalFooter, Button, Modal, Text } from "@opal/components";
import { SvgAlertTriangle, SvgListTree } from "@opal/icons";
import { Section } from "@opal/layouts";
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
          onClose={onClose}
        />
        <Modal.Body>
          <Section gap={2} alignItems="stretch" height="fit">
            <Text as="p" font="main-ui-body" color="text-03">
              {markdown(t("description", { count: failedCount }))}
            </Text>
            <Text as="p" font="main-ui-body" color="text-03">
              {t("proceed")}
            </Text>
          </Section>
        </Modal.Body>
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
