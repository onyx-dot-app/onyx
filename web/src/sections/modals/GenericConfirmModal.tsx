import { Modal } from "@opal/components";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { SvgCheck } from "@opal/icons";
import { useTranslations } from "next-intl";

export interface GenericConfirmModalProps {
  title: string;
  message: string;
  confirmText?: string;
  onClose: () => void;
  onConfirm: () => void;
}

export default function GenericConfirmModal({
  title,
  message,
  confirmText,
  onClose,
  onConfirm,
}: GenericConfirmModalProps) {
  const t = useTranslations("chat.modals.genericConfirm");

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="sm" height="sm">
        <Modal.Header icon={SvgCheck} title={title} onClose={onClose} />
        <Modal.Body>
          <Text as="p">{message}</Text>
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={onConfirm}>
            {confirmText ?? t("confirmButton.label")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
