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
      title={`${model.model_name} already chosen`}
      onOutsideClick={onClose}
    >
      <div className="mb-4">
        <Text className="text-sm mb-2">
          You can select a different one if you want!
        </Text>
        <div className="flex mt-8 justify-between">
          <Button variant="submit" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </Modal>
  );
}
