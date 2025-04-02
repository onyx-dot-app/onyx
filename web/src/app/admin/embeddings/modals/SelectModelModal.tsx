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
      title={`Select ${model.model_name}`}
    >
      <div className="mb-4">
        <Text className="text-lg mb-2">
          You&apos;re selecting a new embedding model, <b>{model.model_name}</b>
          . If you update to this model, you will need to undergo a complete
          re-indexing. Are you sure?
        </Text>
        <div className="flex mt-8 justify-end gap-x-2">
          <Button onClick={onConfirm}>Confirm</Button>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </div>
    </Modal>
  );
}
