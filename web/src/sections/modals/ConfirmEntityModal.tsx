import { ConfirmationModalLayout as Modal } from "@opal/layouts";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { SvgAlertCircle } from "@opal/icons";
import type { IconProps } from "@opal/types";
import { useTranslations } from "next-intl";

export interface ConfirmEntityModalProps {
  danger?: boolean;

  onClose: () => void;
  onSubmit: () => void;

  icon?: React.FunctionComponent<IconProps>;

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

  icon: Icon,

  entityType,
  entityName,

  additionalDetails,

  action,
  actionButtonText,

  removeConfirmationText = false,
}: ConfirmEntityModalProps) {
  const t = useTranslations("chat.modals.confirmEntity");
  const buttonText = actionButtonText
    ? actionButtonText
    : danger
      ? t("deleteButton.label")
      : t("confirmButton.label");
  const actionText = action
    ? action
    : danger
      ? t("deleteAction.label")
      : t("modifyAction.label");

  return (
    <Modal
      icon={Icon || SvgAlertCircle}
      title={t("header.title", { action: buttonText, entityType })}
      onClose={onClose}
      submit={
        <Button variant={danger ? "danger" : "default"} onClick={onSubmit}>
          {buttonText}
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        {!removeConfirmationText && (
          <Text as="p">
            {t.rich("confirmation.description", {
              action: actionText,
              entityName,
              b: (chunks) => <b>{chunks}</b>,
            })}
          </Text>
        )}

        {additionalDetails && (
          <Text as="p" text03>
            {additionalDetails}
          </Text>
        )}
      </div>
    </Modal>
  );
}
