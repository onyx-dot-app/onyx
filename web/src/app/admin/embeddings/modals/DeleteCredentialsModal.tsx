import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";
import React from "react";
import { Modal } from "@/components/Modal";
import Text from "@/components/ui/text";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { CloudEmbeddingProvider } from "../../../../components/embedding/interfaces";

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
      title={`${i18n.t(k.DELETE)} ${modelProvider.provider_type} ${i18n.t(
        k.CREDENTIALS
      )}`}
      onOutsideClick={onCancel}
    >
      <div className="mb-4">
        <Text className="text-lg mb-2">
          {i18n.t(k.YOU_RE_ABOUT_TO_DELETE_YOUR)} {modelProvider.provider_type}{" "}
          {i18n.t(k.CREDENTIALS_ARE_YOU_SURE)}
        </Text>
        <Callout
          type="danger"
          title={i18n.t(k.POINT_OF_NO_RETURN)}
          className="mt-4"
        />
        <div className="flex mt-8 justify-between">
          <Button variant="secondary" onClick={onCancel}>
            {i18n.t(k.KEEP_CREDENTIALS)}
          </Button>
          <Button variant="destructive" onClick={onConfirm}>
            {i18n.t(k.DELETE_CREDENTIALS)}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
