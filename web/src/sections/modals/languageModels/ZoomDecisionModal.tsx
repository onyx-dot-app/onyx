"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  InputSingleSelect,
  MessageCard,
  Modal,
  OnyxLoader,
} from "@opal/components";
import { InputVertical } from "@opal/layouts";
import { SvgZoom } from "@opal/logos";
import { useVoiceProviders } from "@/lib/voice/hooks";
import type { LLMProviderFormProps } from "@/lib/languageModels/types";
import { VoiceProviderSetupModal } from "@/views/admin/VoicePage/shared";

export default function ZoomDecisionModal({
  existingLlmProvider,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const t = useTranslations("admin.decisionModels");
  const { providers, isLoading, error } = useVoiceProviders();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const zoomProviders = providers.filter(
    (provider) => provider.provider_type === "zoom"
  );
  const linkedId = existingLlmProvider?.zoom_voice_provider_id;
  const existingProvider =
    zoomProviders.find(
      (provider) => provider.id === (linkedId ?? selectedId)
    ) ??
    (!linkedId && zoomProviders.length === 1 ? zoomProviders[0] : undefined);
  const close = () => onOpenChange?.(false);

  if (
    !isLoading &&
    !error &&
    (!linkedId || existingProvider) &&
    (zoomProviders.length < 2 || existingProvider)
  ) {
    return (
      <VoiceProviderSetupModal
        providerType="zoom"
        existingProvider={existingProvider ?? null}
        mode="connection"
        onClose={close}
        onSuccess={() => {
          void onSuccess?.();
          close();
        }}
      />
    );
  }

  return (
    <Modal open onOpenChange={close}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgZoom}
          title={t("zoom.title")}
          description={t("zoom.description")}
          onClose={close}
        />
        <Modal.Body>
          {isLoading ? (
            <OnyxLoader size={24} />
          ) : error || linkedId ? (
            <MessageCard variant="error" title={t("loadFailed")} />
          ) : (
            <InputVertical title={t("zoom.connection")}>
              <InputSingleSelect
                value={selectedId === null ? "" : String(selectedId)}
                onValueChange={(value) => setSelectedId(Number(value))}
                placeholder={t("zoom.selectConnection")}
                options={zoomProviders.map((provider) => ({
                  value: String(provider.id),
                  title: provider.name,
                }))}
              />
            </InputVertical>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
