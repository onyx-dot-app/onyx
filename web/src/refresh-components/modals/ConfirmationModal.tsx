import React from "react";
import Text from "@/refresh-components/texts/Text";
import { useEscape } from "@/hooks/useKeyPress";
import Button from "@/refresh-components/buttons/Button";
import Modal, { ModalProps } from "@/refresh-components/modals/Modal";

export interface ConfirmationModalProps extends ModalProps {
  submit: React.ReactNode;
  hideCancel?: boolean;
  onClose: () => void;
}

export default function ConfirmationModal({
  icon,
  title,
  children,

  submit,
  hideCancel,
  onClose,
}: ConfirmationModalProps) {
  useEscape(onClose);

  return (
    <Modal icon={icon} title={title} mini>
      <div className="p-4">
        {typeof children === "string" ? (
          <Text text03>{children}</Text>
        ) : (
          children
        )}
      </div>
      <div className="flex flex-row w-full items-center justify-end p-4 gap-2">
        {!hideCancel && (
          <Button secondary onClick={onClose}>
            Cancel
          </Button>
        )}
        {submit}
      </div>
    </Modal>
  );
}
