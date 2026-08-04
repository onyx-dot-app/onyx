import { Button, Modal, Text } from "@opal/components";
import { SvgAlertTriangle } from "@opal/icons";

interface UnsavedChangesModalProps {
  open: boolean;
  onCancel: () => void;
  onDiscard: () => void;
}

export default function UnsavedChangesModal({
  open,
  onCancel,
  onDiscard,
}: UnsavedChangesModalProps) {
  if (!open) return null;

  return (
    <Modal open>
      <Modal.Content
        width="sm"
        preventAccidentalClose={false}
        onInteractOutside={onCancel}
        onEscapeKeyDown={onCancel}
      >
        <UnsavedChangesModalContent onCancel={onCancel} onDiscard={onDiscard} />
      </Modal.Content>
    </Modal>
  );
}

export function UnsavedChangesModalContent({
  onCancel,
  onDiscard,
}: Omit<UnsavedChangesModalProps, "open">) {
  return (
    <>
      <Modal.Header
        icon={SvgAlertTriangle}
        title="Discard unsaved changes?"
        onClose={onCancel}
      />
      <Modal.Body twoTone>
        <Text as="p" color="text-03">
          Your changes have not been saved. If you leave now, they will be lost.
        </Text>
      </Modal.Body>
      <Modal.Footer>
        <Button type="button" prominence="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="button" variant="danger" onClick={onDiscard}>
          Discard changes
        </Button>
      </Modal.Footer>
    </>
  );
}
