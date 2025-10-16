import Modal from "@/refresh-components/modals/ConfirmationModal";
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

  return (
    <Modal
      icon={SvgAlertCircle}
      title={`${buttonText} ${entityType}`}
      onClose={onClose}
      submit={
        <Button onClick={onSubmit} danger={danger}>
          {buttonText}
        </Button>
      }
    >
      <div className="flex flex-col gap-spacing-paragraph">
        {!removeConfirmationText && (
          <Text>
            Are you sure you want to {actionText} <b>{entityName}</b>?
          </Text>
        )}

        {additionalDetails && <Text text03>{additionalDetails}</Text>}
      </div>
    </Modal>
  );
}
