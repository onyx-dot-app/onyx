import React from "react";
import { Modal } from "@/components/Modal";
import Text from "@/components/ui/text";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import {
  CloudEmbeddingProvider,
  getFormattedProviderName,
} from "../../../../components/embedding/interfaces";

export function DeleteCredentialsModal({
  modelProvider,
  onConfirm,
  onCancel,
}: {
  modelProvider: CloudEmbeddingProvider;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal
      width="max-w-3xl"
      title={`Delete ${getFormattedProviderName(
        modelProvider.provider_type
      )} Credentials?`}
      onOutsideClick={onCancel}
    >
      <div className="mb-4">
        <Text className="text-lg mb-2">
          You&apos;re about to delete your{" "}
          {getFormattedProviderName(modelProvider.provider_type)} credentials.
          Are you sure?
        </Text>
        <Callout type="danger" title="Point of No Return" className="mt-4" />
        <div className="flex mt-8 justify-between">
          <Button variant="secondary" onClick={onCancel}>
            Keep Credentials
          </Button>
          <Button variant="destructive" onClick={onConfirm}>
            Delete Credentials
          </Button>
        </div>
      </div>
    </Modal>
  );
}
