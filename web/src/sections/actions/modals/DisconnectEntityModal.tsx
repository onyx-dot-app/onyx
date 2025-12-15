"use client";

import { useRef } from "react";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
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
          icon={() => (
            <SvgUnplug className="w-[1.5rem] h-[1.5rem] stroke-action-danger-05" />
          )}
          title={`Disconnect ${name}`}
          className="p-4"
          onClose={onClose}
        />

        <Modal.Body className="p-4 flex flex-col gap-2 bg-background-tint-01">
          <Text text03 mainUiBody>
            All tools connected to {name} will stop working. You can reconnect
            to this server later if needed.
          </Text>
          <Text text03 mainUiBody>
            Are you sure you want to proceed?
          </Text>
        </Modal.Body>

        <Modal.Footer className="w-full p-4 gap-2">
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
