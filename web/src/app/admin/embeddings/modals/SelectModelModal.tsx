import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { CloudEmbeddingModel } from "@/components/embedding/interfaces";
import { SvgServer } from "@opal/icons";

export interface SelectModelModalProps {
  model: CloudEmbeddingModel;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function SelectModelModal({
  model,
  onConfirm,
  onCancel,
}: SelectModelModalProps) {
  return (
    <Modal open onOpenChange={onCancel}>
      <Modal.Content small>
        <Modal.Header
          icon={SvgServer}
          title={`Select ${model.model_name}`}
          onClose={onCancel}
        />
        <Modal.Body>
          <Text as="p">
            You&apos;re selecting a new embedding model,{" "}
            <strong>{model.model_name}</strong>. If you update to this model,
            you will need to undergo a complete re-indexing. Are you sure?
          </Text>
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={onConfirm}>Confirm</Button>
          <Button secondary onClick={onCancel}>
            Cancel
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
