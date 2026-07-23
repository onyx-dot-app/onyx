import { Button } from "@opal/components";
import { SvgAlertTriangle } from "@opal/icons";
import { ConfirmationModalLayout } from "@opal/layouts";

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
    <ConfirmationModalLayout
      icon={SvgAlertTriangle}
      title="Discard unsaved changes?"
      onClose={onCancel}
      submit={
        <Button type="button" variant="danger" onClick={onDiscard}>
          Discard changes
        </Button>
      }
    >
      Your changes have not been saved. If you leave now, they will be lost.
    </ConfirmationModalLayout>
  );
}
