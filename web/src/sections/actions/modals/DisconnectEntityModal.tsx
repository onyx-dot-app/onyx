"use client";

import { useRef } from "react";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
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
        mini
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
          title={`Disconnect ${name}`}
          onClose={onClose}
        />

        <Modal.Body>
          <Text as="p" text03 mainUiBody>
            All tools connected to {name} will stop working. You can reconnect
            to this server later if needed.
          </Text>
          <Text as="p" text03 mainUiBody>
            Are you sure you want to proceed?
          </Text>
        </Modal.Body>

        <Modal.Footer>
          <Button main secondary onClick={onClose} disabled={isDisconnecting}>
            Cancel
          </Button>
          {onConfirmDisconnectAndDelete && (
            <Button
              danger
              secondary
              onClick={onConfirmDisconnectAndDelete}
              disabled={isDisconnecting}
            >
              Disconnect &amp; Delete
            </Button>
          )}
          <Button
            danger
            primary
            onClick={onConfirmDisconnect}
            disabled={isDisconnecting}
            ref={disconnectButtonRef}
          >
            {isDisconnecting ? "Disconnecting..." : "Disconnect"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
