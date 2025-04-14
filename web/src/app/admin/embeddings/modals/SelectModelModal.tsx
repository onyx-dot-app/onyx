import i18n from "i18next";
import k from "./../../../../i18n/keys";
import React from "react";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import Text from "@/components/ui/text";
import { CloudEmbeddingModel } from "../../../../components/embedding/interfaces";

export function SelectModelModal({
  model,
  onConfirm,
  onCancel,
}: {
  model: CloudEmbeddingModel;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal
      width="max-w-3xl"
      onOutsideClick={onCancel}
      title={`${i18n.t(k.SELECT)} ${model.model_name}`}
    >
      <div className="mb-4">
        <Text className="text-lg mb-2">
          {i18n.t(k.YOU_RE_SELECTING_A_NEW_EMBEDDI)} <b>{model.model_name}</b>
          {i18n.t(k.IF_YOU_UPDATE_TO_THIS_MODEL)}
        </Text>
        <div className="flex mt-8 justify-end gap-x-2">
          <Button onClick={onConfirm}>{i18n.t(k.CONFIRM)}</Button>
          <Button variant="outline" onClick={onCancel}>
            {i18n.t(k.CANCEL)}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
