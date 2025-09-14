"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";

interface InstantSwitchConfirmModalProps {
  onClose: () => void;
  onConfirm: () => void;
}

export const InstantSwitchConfirmModal = ({
  onClose,
  onConfirm,
}: InstantSwitchConfirmModalProps) => {
  const { t } = useTranslation();
  return (
    <Modal
      onOutsideClick={onClose}
      width="max-w-3xl"
      title={t(k.INSTANT_SWITCH_CONFIRM_TITLE)}
    >
      <>
        <div>
          {t(k.INSTANT_SWITCHING_WILL_IMMEDIA)}

          <br />
          <br />
          <b>{t(k.THIS_IS_NOT_REVERSIBLE)}</b>
        </div>
        <div className="flex mt-4 gap-x-2 justify-end">
          <Button onClick={onConfirm}>{t(k.CONFIRM)}</Button>
          <Button variant="outline" onClick={onClose}>
            {t(k.CANCEL)}
          </Button>
        </div>
      </>
    </Modal>
  );
};
