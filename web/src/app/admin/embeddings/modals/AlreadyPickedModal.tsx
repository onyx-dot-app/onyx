import i18n from "i18next";
import k from "./../../../../i18n/keys";
import React from "react";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import Text from "@/components/ui/text";

import { CloudEmbeddingModel } from "../../../../components/embedding/interfaces";

export function AlreadyPickedModal({
  model,
  onClose,
}: {
  model: CloudEmbeddingModel;
  onClose: () => void;
}) {
  return (
    <Modal
      width="max-w-3xl"
      title={`${model.model_name} ${i18n.t(k.ALREADY_CHOSEN)}`}
      onOutsideClick={onClose}
    >
      <div className="mb-4">
        <Text className="text-sm mb-2">
          {i18n.t(k.YOU_CAN_SELECT_A_DIFFERENT_ONE)}
        </Text>
        <div className="flex mt-8 justify-between">
          <Button variant="submit" onClick={onClose}>
            {i18n.t(k.CLOSE)}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
