import React from "react";
import type { IconProps } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import Modal from "@/refresh-components/Modal";
import { useModalClose } from "../contexts/ModalContext";

export interface ConfirmationModalProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  children?: React.ReactNode;

  submit: React.ReactNode;
  hideCancel?: boolean;
  onClose?: () => void;
}

export default function ConfirmationModalLayout({
  icon,
  title,
  children,

  submit,
  hideCancel,
  onClose: externalOnClose,
}: ConfirmationModalProps) {
  const onClose = useModalClose(externalOnClose);

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose?.()}>
      <Modal.Content mini>
        <Modal.Header icon={icon} title={title} onClose={onClose} />
        <Modal.Body className="p-4">
          {typeof children === "string" ? (
            <Text text03>{children}</Text>
          ) : (
            children
          )}
        </Modal.Body>
        <Modal.Footer className="w-full p-4 gap-2">
          {!hideCancel && (
            <Button secondary onClick={onClose} type="button">
              Cancel
            </Button>
          )}
          {submit}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
