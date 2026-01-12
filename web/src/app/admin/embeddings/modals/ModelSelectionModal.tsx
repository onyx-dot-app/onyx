import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { Callout } from "@/components/ui/callout";
import Button from "@/refresh-components/buttons/Button";
import { HostedEmbeddingModel } from "@/components/embedding/interfaces";
import { SvgServer } from "@opal/icons";

export interface ModelSelectionConfirmationModalProps {
  selectedModel: HostedEmbeddingModel;
  isCustom: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ModelSelectionConfirmationModal({
  selectedModel,
  isCustom,
  onConfirm,
  onCancel,
}: ModelSelectionConfirmationModalProps) {
  return (
    <Modal open onOpenChange={onCancel}>
      <Modal.Content tall>
        <Modal.Header
          icon={SvgServer}
          title="Update Embedding Model"
          onClose={onCancel}
        />
        <Modal.Body>
          <Text as="p">
            You have selected: <strong>{selectedModel.model_name}</strong>. Are
            you sure you want to update to this new embedding model?
          </Text>
          <Text as="p">
            We will re-index all your documents in the background so you will be
            able to continue to use Onyx as normal with the old model in the
            meantime. Depending on how many documents you have indexed, this may
            take a while.
          </Text>
          <Text as="p">
            <i>NOTE:</i> this re-indexing process will consume more resources
            than normal. If you are self-hosting, we recommend that you allocate
            at least 16GB of RAM to Onyx during this process.
          </Text>

          {isCustom && (
            <Callout type="warning" title="IMPORTANT">
              We&apos;ve detected that this is a custom-specified embedding
              model. Since we have to download the model files before verifying
              the configuration&apos;s correctness, we won&apos;t be able to let
              you know if the configuration is valid until{" "}
              <strong>after</strong> we start re-indexing your documents. If
              there is an issue, it will show up on this page as an indexing
              error on this page after clicking Confirm.
            </Callout>
          )}
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
