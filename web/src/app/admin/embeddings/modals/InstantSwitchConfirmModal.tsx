import i18n from "i18next";
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
  return (
    <Modal
      onOutsideClick={onClose}
      width="max-w-3xl"
      title="Are you sure you want to do an instant switch?"
    >
      <>
        <div>
          {i18n.t(k.INSTANT_SWITCHING_WILL_IMMEDIA)}

          <br />
          <br />
          <b>{i18n.t(k.THIS_IS_NOT_REVERSIBLE)}</b>
        </div>
        <div className="flex mt-4 gap-x-2 justify-end">
          <Button onClick={onConfirm}>{i18n.t(k.CONFIRM)}</Button>
          <Button variant="outline" onClick={onClose}>
            {i18n.t(k.CANCEL)}
          </Button>
        </div>
      </>
    </Modal>
  );
};
