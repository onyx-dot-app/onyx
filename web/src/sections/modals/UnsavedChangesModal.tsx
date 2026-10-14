import { Button, Modal, Text } from "@opal/components";
import { SvgAlertTriangle } from "@opal/icons";
import { useTranslations } from "next-intl";

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
  const t = useTranslations("chat.modals.unsavedChanges");

  return (
    <>
      <Modal.Header
        icon={SvgAlertTriangle}
        title={t("header.title")}
        onClose={onCancel}
      />
      <Modal.Body twoTone>
        <Text as="p" color="text-03">
          {t("body.description")}
        </Text>
      </Modal.Body>
      <Modal.Footer>
        <Button type="button" prominence="secondary" onClick={onCancel}>
          {t("cancelButton.label")}
        </Button>
        <Button type="button" variant="danger" onClick={onDiscard}>
          {t("discardButton.label")}
        </Button>
      </Modal.Footer>
    </>
  );
}
