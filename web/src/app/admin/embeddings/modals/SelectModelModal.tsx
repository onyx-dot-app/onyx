import React from "react";
import { Modal } from "@/components/Modal";
import { Button, Text } from "@tremor/react";
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
      title={`Select ${model.model_name}`}
    >
      <div className="mb-4">
        <Text className="text-lg mb-2">
          You&apos;re selecting a new embedding model, {model.model_name}. If
          you update to this model, you will need to undergo a complete
          re-indexing.
          <br />
          Are you sure?
        </Text>
        <div className="flex mt-8 justify-end">
          <Button color="green" onClick={onConfirm}>
            Yes
          </Button>
        </div>
      </div>
    </Modal>
  );
}
