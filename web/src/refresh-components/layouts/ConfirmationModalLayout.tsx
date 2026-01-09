import React from "react";
import type { IconProps } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import Modal from "@/refresh-components/Modal";
import { useModalClose } from "../contexts/ModalContext";
import { Section } from "@/layouts/general-layouts";

export interface ConfirmationModalProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description?: string;
  children?: React.ReactNode;

  submit: React.ReactNode;
  hideCancel?: boolean;
  onClose?: () => void;
}

export default function ConfirmationModalLayout({
  icon,
  title,
  description,
  children,

  submit,
  hideCancel,
  onClose: externalOnClose,
}: ConfirmationModalProps) {
  const onClose = useModalClose(externalOnClose);

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose?.()}>
      <Modal.Content mini>
        <Modal.Header
          icon={icon}
          title={title}
          description={description}
          onClose={onClose}
        />
        <Modal.Body>
          {typeof children === "string" ? (
            <Text as="p" text03>
              {children}
            </Text>
          ) : (
            children
          )}
        </Modal.Body>
        <Modal.Footer>
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
