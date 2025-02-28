import React, { useState } from "react";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import Text from "@/components/ui/text";
import { CloudEmbeddingModel } from "../../../../components/embedding/interfaces";
import { Checkbox } from "@/components/ui/checkbox";

export function SelectModelModal({
  model,
  onConfirm,
  onCancel,
}: {
  model: CloudEmbeddingModel;
  onConfirm: (requiresReindex: boolean) => void;
  onCancel: () => void;
}) {
  const [requiresReindex, setRequiresReindex] = useState(true);

  return (
    <Modal
      width="max-w-3xl"
      onOutsideClick={onCancel}
      title={`Select ${model.model_name}`}
    >
      <div className="mb-4">
        <Text className="text-lg mb-4">
          You&apos;re selecting a new embedding model, {model.model_name}.
        </Text>

        <div className="flex items-center space-x-2 mb-4">
          <Checkbox
            id="requires-reindex"
            checked={requiresReindex}
            onCheckedChange={(checked) =>
              setRequiresReindex(checked as boolean)
            }
          />
          <label
            htmlFor="requires-reindex"
            className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
          >
            Re-index documents with new model
          </label>
        </div>

        <Text className="text-sm text-neutral-500 mb-4">
          {requiresReindex
            ? "This will trigger a complete re-indexing of all documents. The re-indexing will happen in the background - your use of Onyx will not be interrupted."
            : "The new model will only be used for new documents and queries. Existing document embeddings will not be updated."}
        </Text>

        <div className="flex mt-8 justify-end">
          <Button variant="submit" onClick={() => onConfirm(requiresReindex)}>
            Yes
          </Button>
        </div>
      </div>
    </Modal>
  );
}
