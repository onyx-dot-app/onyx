"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  BasicModalFooter,
  Button,
  InputSingleSelect,
  MessageCard,
  Modal,
  OnyxLoader,
} from "@opal/components";
import { InputVertical, Section, toast } from "@opal/layouts";
import { SvgZoom } from "@opal/logos";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useVoiceProviders } from "@/lib/voice/hooks";
import { useWellKnownLLMProvider } from "@/lib/languageModels/hooks";
import { LLMProviderName } from "@/lib/languageModels/types";
import type { LLMProviderFormProps } from "@/lib/languageModels/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { parseErrorDetail } from "@/lib/fetcher";

export default function ZoomDecisionModal({
  existingLlmProvider,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const t = useTranslations("admin.decisionModels");
  const { providers, isLoading, error } = useVoiceProviders();
  const {
    wellKnownLLMProvider,
    error: modelsError,
    isLoading: modelsLoading,
  } = useWellKnownLLMProvider(LLMProviderName.ZOOM_AI);
  const models =
    existingLlmProvider?.model_configurations ??
    wellKnownLLMProvider?.known_models ??
    [];
  const [selected, setSelected] = useState(
    String(existingLlmProvider?.zoom_voice_provider_id ?? "")
  );
  const [pending, setPending] = useState(false);
  const zoomProviders = providers.filter(
    (provider) => provider.provider_type === "zoom"
  );
  const close = () => onOpenChange?.(false);

  async function save() {
    if (!selected || pending) return;
    setPending(true);
    try {
      const response = await fetch(
        SWR_KEYS.adminLlmProviders +
          (existingLlmProvider ? "" : "?is_creation=true"),
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id: existingLlmProvider?.id,
            provider: "zoom_ai",
            name: existingLlmProvider?.name ?? null,
            zoom_voice_provider_id: Number(selected),
            is_public: true,
            is_auto_mode: false,
            model_configuration_scope: "decision",
            model_configurations: models.map((model) => ({
              ...model,
              is_visible: false,
            })),
          }),
        }
      );
      if (!response.ok)
        throw new Error(await parseErrorDetail(response, t("saveFailed")));
      await onSuccess?.();
      close();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("saveFailed"));
    } finally {
      setPending(false);
    }
  }

  return (
    <Modal open onOpenChange={close}>
      <Modal.Content width="md">
        <Modal.Header
          icon={SvgZoom}
          title={t("zoom.title")}
          description={t("zoom.description")}
          onClose={close}
        />
        <Modal.Body>
          <Section gap={3} alignItems="stretch">
            {isLoading || modelsLoading ? (
              <OnyxLoader size={24} />
            ) : error || modelsError ? (
              <MessageCard variant="error" title={t("loadFailed")} />
            ) : zoomProviders.length > 0 ? (
              <InputVertical title={t("zoom.connection")}>
                <InputSingleSelect
                  value={selected}
                  onValueChange={setSelected}
                  placeholder={t("zoom.selectConnection")}
                  options={zoomProviders.map((provider) => ({
                    value: String(provider.id),
                    title: provider.name,
                  }))}
                />
              </InputVertical>
            ) : (
              <MessageCard
                title={t("zoom.noConnections")}
                rightChildren={
                  <Button href={ADMIN_ROUTES.VOICE.path} prominence="secondary">
                    {t("zoom.setupVoice")}
                  </Button>
                }
              />
            )}
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button prominence="secondary" onClick={close}>
                {t("cancel")}
              </Button>
            }
            submit={
              <Button
                disabled={!selected || pending || models.length === 0}
                onClick={() => void save()}
              >
                {t("save")}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
