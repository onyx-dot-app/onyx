import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import SvgCheck from "@/icons/check";

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
      <Modal.Content small>
        <Modal.Header icon={SvgCheck} title={title} onClose={onClose} />
        <Modal.Body>
          <Text>{message}</Text>
        </Modal.Body>
        <Modal.Footer className="p-4">
          <Button onClick={onConfirm}>{confirmText}</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
