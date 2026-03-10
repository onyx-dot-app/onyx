"use client";

import React from "react";
import type { IconProps } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
import Modal from "@/refresh-components/Modal";
import { useModalClose } from "../contexts/ModalContext";

export interface ConfirmationModalProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description?: string;
  children?: React.ReactNode;

  submit: React.ReactNode;
  hideCancel?: boolean;
  onClose?: () => void;
  /** If false, removes the gray background from the body. Defaults to true. */
  twoTone?: boolean;
}

export default function ConfirmationModalLayout({
  icon,
  title,
  description,
  children,

  submit,
  hideCancel,
  onClose: externalOnClose,
  twoTone = true,
}: ConfirmationModalProps) {
  const onClose = useModalClose(externalOnClose);

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose?.()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={icon}
          title={title}
          description={description}
          onClose={onClose}
        />
        <Modal.Body twoTone={twoTone}>
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
            <Button prominence="secondary" onClick={onClose}>
              Cancel
            </Button>
          )}
          {submit}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
