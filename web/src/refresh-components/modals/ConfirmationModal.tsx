import React from "react";
import { SvgProps } from "@/icons";
import Text from "@/refresh-components/texts/Text";
import { Modal } from "@/refresh-components/modals/NewModal";
import Button from "@/refresh-components/buttons/Button";

interface ConfirmationModalProps {
  escapeToClose?: boolean;
  clickOutsideToClose?: boolean;

  icon: React.FunctionComponent<SvgProps>;
  title: string;
  children?: React.ReactNode;

  submit: React.ReactNode;
  hideCancel?: boolean;
  onClose: () => void;
}

export default function ConfirmationModal({
  escapeToClose = true,
  clickOutsideToClose = true,

  icon,
  title,
  children,

  submit,
  hideCancel,
  onClose,
}: ConfirmationModalProps) {
  const handleOpenChange = (open: boolean) => {
    if (!open) {
      onClose();
    }
  };

  return (
    <Modal open onOpenChange={handleOpenChange}>
      <Modal.Content
        size="xs"
        onOpenAutoFocus={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => {
          if (!escapeToClose) {
            e.preventDefault();
          }
        }}
        onPointerDownOutside={(e) => {
          if (!clickOutsideToClose) {
            e.preventDefault();
          }
        }}
      >
        <Modal.CloseButton />

        <Modal.Header className="flex flex-col p-4 gap-1">
          <Modal.Icon icon={icon} />
          <Modal.Title>{title}</Modal.Title>
        </Modal.Header>

        <Modal.Body className="px-4 pb-4">
          {typeof children === "string" ? (
            <Text text03>{children}</Text>
          ) : (
            children
          )}
        </Modal.Body>

        <Modal.Footer className="flex flex-row w-full items-center justify-end px-4 pb-4 gap-2">
          {!hideCancel && (
            <Button secondary onClick={onClose}>
              Cancel
            </Button>
          )}
          {submit}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
