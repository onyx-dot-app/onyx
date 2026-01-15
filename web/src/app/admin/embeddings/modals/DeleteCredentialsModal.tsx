import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { Callout } from "@/components/ui/callout";
import {
  CloudEmbeddingProvider,
  getFormattedProviderName,
} from "../../../../components/embedding/interfaces";
import { SvgTrash } from "@opal/icons";

export interface DeleteCredentialsModalProps {
  modelProvider: CloudEmbeddingProvider;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function DeleteCredentialsModal({
  modelProvider,
  onConfirm,
  onCancel,
}: DeleteCredentialsModalProps) {
  return (
    <Modal open onOpenChange={onCancel}>
      <Modal.Content small>
        <Modal.Header
          icon={SvgTrash}
          title={`Delete ${getFormattedProviderName(
            modelProvider.provider_type
          )} Credentials?`}
          onClose={onCancel}
        />
        <Modal.Body>
          <Text as="p">
            You&apos;re about to delete your{" "}
            {getFormattedProviderName(modelProvider.provider_type)} credentials.
            Are you sure?
          </Text>
          <Callout type="danger" title="Point of No Return" />
        </Modal.Body>
        <Modal.Footer>
          <Button secondary onClick={onCancel}>
            Keep Credentials
          </Button>
          <Button danger onClick={onConfirm}>
            Delete Credentials
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
