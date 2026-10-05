"use client";

import { useRef } from "react";
import { useTranslations } from "next-intl";
import { Modal } from "@opal/components";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@opal/utils";
import { markdown } from "@opal/utils";
import { SvgUnplug } from "@opal/icons";
interface DisconnectEntityModalProps {
  isOpen: boolean;
  onClose: () => void;
  name: string | null;
  onConfirmDisconnect: () => void;
  onConfirmDisconnectAndDelete?: () => void;
  isDisconnecting?: boolean;
  skipOverlay?: boolean;
}

export default function DisconnectEntityModal({
  isOpen,
  onClose,
  name,
  onConfirmDisconnect,
  onConfirmDisconnectAndDelete,
  isDisconnecting = false,
  skipOverlay = false,
}: DisconnectEntityModalProps) {
  const t = useTranslations("actions");
  const disconnectButtonRef = useRef<HTMLButtonElement>(null);

  if (!name) return null;

  return (
    <Modal
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
    >
      <Modal.Content
        width="sm"
        preventAccidentalClose={false}
        skipOverlay={skipOverlay}
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          disconnectButtonRef.current?.focus();
        }}
      >
        <Modal.Header
          icon={({ className }) => (
            <SvgUnplug className={cn(className, "stroke-action-danger-05")} />
          )}
          title={markdown(t("disconnectModal.header.title", { name }))}
          onClose={onClose}
        />

        <Modal.Body>
          <Text as="p" text03 mainUiBody>
            {t("disconnectModal.body.description", { name })}
          </Text>
          <Text as="p" text03 mainUiBody>
            {t("disconnectModal.body.confirmation")}
          </Text>
        </Modal.Body>

        <Modal.Footer>
          <Button
            disabled={isDisconnecting}
            prominence="secondary"
            onClick={onClose}
          >
            {t("disconnectModal.cancelButton.label")}
          </Button>
          {onConfirmDisconnectAndDelete && (
            <Button
              disabled={isDisconnecting}
              variant="danger"
              prominence="secondary"
              onClick={onConfirmDisconnectAndDelete}
            >
              {t("disconnectModal.deleteButton.label")}
            </Button>
          )}
          <Button
            disabled={isDisconnecting}
            variant="danger"
            onClick={onConfirmDisconnect}
            ref={disconnectButtonRef}
          >
            {isDisconnecting
              ? t("disconnectModal.confirmButton.pendingLabel")
              : t("disconnectModal.confirmButton.label")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
