import i18n from "@/i18n/init";
import k from "./../i18n/keys";
import React from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/Modal";

interface DeleteEntityModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  entityType: "file" | "folder";
  entityName: string;
  additionalWarning?: string;
}

export const DeleteEntityModal: React.FC<DeleteEntityModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  entityType,
  entityName,
  additionalWarning,
}) => {
  if (!isOpen) return null;

  return (
    <Modal
      onOutsideClick={onClose}
      width="max-w-md w-full"
      hideDividerForTitle
      noPadding
    >
      <>
        <div className="p-6">
          <h2 className="text-xl font-bold mb-4">
            {i18n.t(k.DELETE)} {entityType}
          </h2>
          <p className="mb-6 line-wrap break-words">
            {i18n.t(k.ARE_YOU_SURE_YOU_WANT_TO_DELET1)} {entityType}{" "}
            {i18n.t(k._17)}
            {entityName}
            {i18n.t(k.THIS_ACTION_CANNOT_BE_UNDON)}
            {additionalWarning}
          </p>
          <div className="flex justify-end space-x-4">
            <Button onClick={onClose} variant="outline">
              {i18n.t(k.CANCEL)}
            </Button>
            <Button onClick={onConfirm} variant="destructive">
              {i18n.t(k.DELETE)}
            </Button>
          </div>
        </div>
      </>
    </Modal>
  );
};
