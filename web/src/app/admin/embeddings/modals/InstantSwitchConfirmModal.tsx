import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import SvgAlertTriangle from "@/icons/alert-triangle";

export interface InstantSwitchConfirmModalProps {
  onClose: () => void;
  onConfirm: () => void;
}

export default function InstantSwitchConfirmModal({
  onClose,
  onConfirm,
}: InstantSwitchConfirmModalProps) {
  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content small>
        <Modal.Header
          icon={SvgAlertTriangle}
          title="Are you sure you want to do an instant switch?"
          onClose={onClose}
        />
        <Modal.Body>
          <Text>
            Instant switching will immediately change the embedding model
            without re-indexing. Searches will be over a partial set of
            documents (starting with 0 documents) until re-indexing is complete.
          </Text>
          <Text>
            <strong>This is not reversible.</strong>
          </Text>
        </Modal.Body>
        <Modal.Footer className="p-4 gap-2">
          <Button onClick={onConfirm}>Confirm</Button>
          <Button secondary onClick={onClose}>
            Cancel
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
