import Modal from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";

interface ModalFormFooterProps {
  onClose: () => void;
  isFormValid: boolean;
  isTesting?: boolean;
  testError?: string;
}

export function ModalFormFooter({
  onClose,
  isFormValid,
  isTesting,
  testError,
}: ModalFormFooterProps) {
  return (
    <>
      {testError && (
        <Text as="p" className="text-status-error-05 px-4">
          {testError}
        </Text>
      )}
      <Modal.Footer>
        <Button prominence="secondary" onClick={onClose} type="button">
          Cancel
        </Button>
        <Button type="submit" disabled={!isFormValid || isTesting}>
          {isTesting ? "Connecting..." : "Connect"}
        </Button>
      </Modal.Footer>
    </>
  );
}
