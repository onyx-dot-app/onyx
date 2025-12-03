"use client";

import DisconnectEntityModal from "./DisconnectEntityModal";
import { MCPServerWithStatus } from "@/lib/tools/types";

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
  return (
    <DisconnectEntityModal
      isOpen={isOpen}
      onClose={onClose}
      name={server?.name ?? null}
      onConfirmDisconnect={onConfirmDisconnect}
      onConfirmDisconnectAndDelete={onConfirmDisconnectAndDelete}
      isDisconnecting={isDisconnecting}
      skipOverlay={skipOverlay}
    />
  );
}
