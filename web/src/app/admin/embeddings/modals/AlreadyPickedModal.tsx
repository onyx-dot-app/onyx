import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import SvgCheck from "@/icons/check";
import { CloudEmbeddingModel } from "../../../../components/embedding/interfaces";

export interface AlreadyPickedModalProps {
  model: CloudEmbeddingModel;
  onClose: () => void;
}

export default function AlreadyPickedModal({
  model,
  onClose,
}: AlreadyPickedModalProps) {
  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content small>
        <Modal.Header
          icon={SvgCheck}
          title={`${model.model_name} already chosen`}
          description="You can select a different one if you want!"
          onClose={onClose}
        />
        <Modal.Footer>
          <Button onClick={onClose}>Close</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
