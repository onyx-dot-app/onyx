import { Modal } from "@/refresh-components/modals/NewModal";
import Button from "@/refresh-components/buttons/Button";
import SvgAlertCircle from "@/icons/alert-circle";
import Text from "@/refresh-components/texts/Text";

export interface ConfirmEntityModalProps {
  danger?: boolean;

  onClose: () => void;
  onSubmit: () => void;

  entityType: string;
  entityName: string;

  additionalDetails?: string;

  action?: string;
  actionButtonText?: string;

  removeConfirmationText?: boolean;
}

export function ConfirmEntityModal({
  danger,

  onClose,
  onSubmit,

  entityType,
  entityName,

  additionalDetails,

  action,
  actionButtonText,

  removeConfirmationText = false,
}: ConfirmEntityModalProps) {
  const buttonText = actionButtonText
    ? actionButtonText
    : danger
      ? "Delete"
      : "Confirm";
  const actionText = action ? action : danger ? "delete" : "modify";

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      onClose();
    }
  };

  return (
    <Modal open onOpenChange={handleOpenChange}>
      <Modal.Content size="xs" onOpenAutoFocus={(e) => e.preventDefault()}>
        <Modal.CloseButton />

        <Modal.Header className="flex flex-col p-4 gap-1">
          <Modal.Icon icon={SvgAlertCircle} />
          <Modal.Title>{`${buttonText} ${entityType}`}</Modal.Title>
        </Modal.Header>

        <Modal.Body className="px-4 pb-4">
          <div className="flex flex-col gap-4">
            {!removeConfirmationText && (
              <Text>
                Are you sure you want to {actionText} <b>{entityName}</b>?
              </Text>
            )}

            {additionalDetails && <Text text03>{additionalDetails}</Text>}
          </div>
        </Modal.Body>

        <Modal.Footer className="flex flex-row w-full items-center justify-end px-4 pb-4 gap-2">
          <Button secondary onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={onSubmit} danger={danger}>
            {buttonText}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
