import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { SvgAlertTriangle } from "@opal/icons";
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
          <Text as="p">
            Instant switching will immediately change the embedding model
            without re-indexing. Searches will be over a partial set of
            documents (starting with 0 documents) until re-indexing is complete.
          </Text>
          <Text as="p">
            <strong>This is not reversible.</strong>
          </Text>
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={onConfirm}>Confirm</Button>
          <Button secondary onClick={onClose}>
            Cancel
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
