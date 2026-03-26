import Modal from "@/refresh-components/Modal";
import { Button, Text } from "@opal/components";
import { SvgCheck } from "@opal/icons";
export interface GenericConfirmModalProps {
  title: string;
  message: string;
  confirmText?: string;
  onClose: () => void;
  onConfirm: () => void;
}

export default function GenericConfirmModal({
  title,
  message,
  confirmText = "Confirm",
  onClose,
  onConfirm,
}: GenericConfirmModalProps) {
  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="sm" height="sm">
        <Modal.Header icon={SvgCheck} title={title} onClose={onClose} />
        <Modal.Body>
          <Text as="p" color="text-05">
            {message}
          </Text>
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={onConfirm}>{confirmText}</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
