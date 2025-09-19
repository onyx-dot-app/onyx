"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";
import { Modal } from "@/components/Modal";
import Text from "@/components/ui/text";
import { Callout } from "@/components/ui/callout";
import { Button } from "@/components/ui/button";
import { HostedEmbeddingModel } from "../../../../components/embedding/interfaces";

export function ModelSelectionConfirmationModal({
  selectedModel,
  isCustom,
  onConfirm,
  onCancel,
}: {
  selectedModel: HostedEmbeddingModel;
  isCustom: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Modal
      width="max-w-3xl"
      title={t(k.EMBEDDING_MODEL_UPDATE_TITLE)}
      onOutsideClick={onCancel}
    >
      <div>
        <div className="mb-4">
          <Text className="text-lg mb-4">
            {t(k.YOU_HAVE_SELECTED)} <b>{selectedModel.model_name}</b>
            {t(k.ARE_YOU_SURE_YOU)}
          </Text>
          <Text className="text-lg mb-2">
            {t(k.WE_WILL_RE_INDEX_ALL_YOUR_DOCU)}
          </Text>
          <Text className="text-lg mb-2">
            <i>{t(k.NOTE)}</i> {t(k.THIS_RE_INDEXING_PROCESS_WILL)}
          </Text>

          {isCustom && (
            <Callout
              type="warning"
              title={t(k.IMPORTANT_WARNING)}
              className="mt-4"
            >
              {t(k.WE_VE_DETECTED_THAT_THIS_IS_A)}
              <b>{t(k.AFTER)}</b> {t(k.WE_START_RE_INDE)}
            </Callout>
          )}

          <div className="flex mt-8 gap-x-2 justify-end">
            <Button onClick={onConfirm}>{t(k.CONFIRM)}</Button>
            <Button variant="outline" onClick={onCancel}>
              {t(k.CANCEL)}
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
