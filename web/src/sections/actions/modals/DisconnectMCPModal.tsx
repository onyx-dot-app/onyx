"use client";

import { useRef } from "react";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import SvgUnplug from "@/icons/unplug";
import { MCPServerWithStatus } from "@/sections/actions/types";

interface DisconnectMCPModalProps {
  isOpen: boolean;
  onClose: () => void;
  server: MCPServerWithStatus | null;
  onConfirmDisconnect: () => void;
  onConfirmDisconnectAndDelete: () => void;
  isDisconnecting?: boolean;
  skipOverlay?: boolean;
}

export default function DisconnectMCPModal({
  isOpen,
  onClose,
  server,
  onConfirmDisconnect,
  onConfirmDisconnectAndDelete,
  isDisconnecting = false,
  skipOverlay = false,
}: DisconnectMCPModalProps) {
  const disconnectButtonRef = useRef<HTMLButtonElement>(null);

  if (!server) return null;

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
          icon={SvgUnplug}
          title={`Disconnect ${server.name}`}
          className="p-4"
          onClose={onClose}
        />

        <Modal.Body className="p-4 flex flex-col gap-2 bg-background-tint-01">
          <Text text03 mainUiBody>
            All tools connected to {server.name} will stop working. You can
            reconnect to this server later if needed.
          </Text>
          <Text text03 mainUiBody>
            Are you sure you want to proceed?
          </Text>
        </Modal.Body>

        <Modal.Footer className="p-4 gap-2">
          <Button main secondary onClick={onClose} disabled={isDisconnecting}>
            Cancel
          </Button>
          <Button
            danger
            secondary
            onClick={onConfirmDisconnectAndDelete}
            disabled={isDisconnecting}
          >
            Disconnect & Delete
          </Button>
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
