"use client";

import { markdown } from "@opal/utils";
import { useEffect, useState } from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { GlomiLogoMark } from "@/refresh-components/GlomiLogo";
import Modal from "@/refresh-components/Modal";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import InputComboBoxField from "@/refresh-components/form/InputComboBoxField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { InputVertical } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { SvgArrowExchange, SvgUnplug, SvgSimpleLoader } from "@opal/icons";
import { Button, Text } from "@opal/components";
import { toast } from "@/hooks/useToast";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";
import type {
  VoiceProviderView,
  VoiceFormValues,
  VoiceOption,
} from "@/lib/voice/types";
import {
  testVoiceProvider,
  upsertVoiceProvider,
  fetchVoicesByType,
  deleteVoiceProvider,
} from "@/lib/voice/svc";
import {
  getVoiceProviderDetail,
  resolveModelId,
  type ProviderMode,
} from "@/lib/voice/utils";

export { type ProviderMode } from "@/lib/voice/utils";

// ---------------------------------------------------------------------------
// VoiceProviderSetupModal
// ---------------------------------------------------------------------------

interface VoiceProviderSetupModalProps {
  providerType: string;
  existingProvider: VoiceProviderView | null;
  mode: ProviderMode;
  defaultModelId?: string | null;
  onSuccess: () => void;
}

export function VoiceProviderSetupModal({
  providerType,
  existingProvider,
  mode,
  defaultModelId,
  onSuccess,
}: VoiceProviderSetupModalProps) {
  const onClose = useModalClose();
  const detail = getVoiceProviderDetail(providerType);
  const initialTtsModel = defaultModelId
    ? resolveModelId(defaultModelId)
    : (existingProvider?.tts_model ?? "tts-1");

  const isEditing = !!existingProvider;

  // Non-form state: dynamic voice options
  const [voiceOptions, setVoiceOptions] = useState<VoiceOption[]>([]);
  const [isLoadingVoices, setIsLoadingVoices] = useState(false);
  const [initialDefaultVoice, setInitialDefaultVoice] = useState(
    existingProvider?.default_voice ?? ""
  );

  // Fetch voices on mount
  useEffect(() => {
    setIsLoadingVoices(true);
    fetchVoicesByType(providerType)
      .then((res) => res.json())
      .then((data: Array<{ id: string; name: string }>) => {
        const options = data.map((v) => ({
          value: v.id,
          label: v.name,
          description: v.id,
        }));
        setVoiceOptions(options);
        setInitialDefaultVoice((prev) => {
          if (!prev) return options[0]?.value ?? "";
          return options.some((o) => o.value === prev)
            ? prev
            : (options[0]?.value ?? "");
        });
      })
      .catch(() => setVoiceOptions([]))
      .finally(() => setIsLoadingVoices(false));
  }, [providerType]);

  const validationSchema = Yup.object().shape({
    api_key: Yup.string().required("请输入 API Key"),
    target_uri:
      providerType === "azure"
        ? Yup.string().required("请输入目标 URI")
        : Yup.string(),
    stt_model: Yup.string(),
    tts_model: Yup.string(),
    default_voice: Yup.string(),
  });

  const initialValues: VoiceFormValues = {
    api_key: existingProvider?.api_key ?? "",
    target_uri: existingProvider?.target_uri ?? "",
    stt_model: existingProvider?.stt_model ?? "whisper-1",
    tts_model: initialTtsModel,
    default_voice: initialDefaultVoice,
  };

  async function handleSubmit(
    values: VoiceFormValues,
    { setSubmitting }: { setSubmitting: (v: boolean) => void }
  ) {
    const apiKeyChanged = values.api_key !== (existingProvider?.api_key ?? "");
    const shouldUseStoredKey = !apiKeyChanged && !!existingProvider?.api_key;

    try {
      if (!shouldUseStoredKey) {
        const testResponse = await testVoiceProvider({
          provider_type: providerType,
          api_key: apiKeyChanged ? values.api_key : undefined,
          target_uri: values.target_uri || undefined,
          use_stored_key: shouldUseStoredKey,
        });

        if (!testResponse.ok) {
          const data = await testResponse.json().catch(() => ({}));
          toast.error(
            typeof data?.detail === "string"
              ? data.detail
              : "连接测试失败"
          );
          setSubmitting(false);
          return;
        }
      }

      const response = await upsertVoiceProvider({
        id: existingProvider?.id,
        name: detail.label,
        provider_type: providerType,
        api_key: apiKeyChanged ? values.api_key : undefined,
        api_key_changed: apiKeyChanged,
        target_uri: values.target_uri || undefined,
        stt_model: values.stt_model,
        tts_model: values.tts_model,
        default_voice: values.default_voice,
        activate_stt: isEditing
          ? (existingProvider?.is_default_stt ?? false)
          : mode === "stt",
        activate_tts: isEditing
          ? (existingProvider?.is_default_tts ?? false)
          : mode === "tts",
      });

      if (response.ok) {
        onSuccess();
      } else {
        const data = await response.json().catch(() => ({}));
        toast.error(
          typeof data?.detail === "string"
            ? data.detail
            : "保存服务商失败"
        );
      }
    } catch {
      toast.error("保存服务商失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="sm">
        <Formik
          initialValues={initialValues}
          validationSchema={validationSchema}
          enableReinitialize
          onSubmit={handleSubmit}
        >
          {({ isSubmitting, dirty, isValid }) => (
            <Form>
              <Modal.Header
                icon={detail.icon}
                moreIcon1={SvgArrowExchange}
                moreIcon2={GlomiLogoMark}
                title={
                  isEditing
                    ? `配置 ${detail.label}`
                    : `设置 ${detail.label}`
                }
                description={`连接 ${detail.label} 并设置语音模型。`}
                onClose={onClose}
              />
              <Modal.Body>
                <Section gap={1} alignItems="stretch">
                  {providerType === "azure" && (
                    <InputVertical
                      title="目标 URI"
                      subDescription={markdown(
                        "Paste the endpoint shown in [Azure Portal (Keys and Endpoint)](https://portal.azure.com/). Glomi AI extracts the speech region from this URL. Examples: `https://westus.api.cognitive.microsoft.com/` or `https://westus.tts.speech.microsoft.com/`."
                      )}
                      withLabel="target_uri"
                    >
                      <InputTypeInField
                        name="target_uri"
                        placeholder="https://your_resource_region.tts.speech.microsoft.com/"
                      />
                    </InputVertical>
                  )}

                  <InputVertical
                    title="API Key"
                    subDescription={markdown(
                      `粘贴来自 ${detail.label} 的 [API Key](${detail.apiKeyUrl}) 来访问模型。`
                    )}
                    withLabel="api_key"
                  >
                    <PasswordInputTypeInField
                      name="api_key"
                      placeholder="API key"
                    />
                  </InputVertical>

                  {mode === "stt" && (detail.sttModels?.length ?? 0) > 1 && (
                    <InputVertical title="STT Model" withLabel="stt_model">
                      <InputSelectField name="stt_model">
                        <InputSelect.Trigger />
                        <InputSelect.Content>
                          {detail.sttModels!.map((m) => (
                            <InputSelect.Item key={m.id} value={m.id}>
                              {m.name}
                            </InputSelect.Item>
                          ))}
                        </InputSelect.Content>
                      </InputSelectField>
                    </InputVertical>
                  )}

                  {mode === "tts" && (
                    <>
                      {(detail.ttsModels?.length ?? 0) > 1 && (
                        <InputVertical
                          title="默认模型"
                          subDescription="Glomi AI 默认会使用此模型进行文本转语音。"
                          withLabel="tts_model"
                        >
                          <InputSelectField name="tts_model">
                            <InputSelect.Trigger />
                            <InputSelect.Content>
                              {detail.ttsModels!.map((m) => (
                                <InputSelect.Item key={m.id} value={m.id}>
                                  {m.name}
                                </InputSelect.Item>
                              ))}
                            </InputSelect.Content>
                          </InputSelectField>
                        </InputVertical>
                      )}

                      <InputVertical
                        title="声音"
                        subDescription={markdown(
                          `此声音将用于语音回复。你可以在 [${
                            detail.voiceDocsUrl?.label ?? detail.label
                          }](${detail.voiceDocsUrl?.url ?? detail.docsUrl}) 查看支持的语言和声音列表。`
                        )}
                        withLabel="default_voice"
                      >
                        <InputComboBoxField
                          name="default_voice"
                          options={voiceOptions}
                          placeholder={
                            isLoadingVoices
                              ? "正在加载声音..."
                              : "选择声音或输入声音 ID"
                          }
                          disabled={isLoadingVoices}
                          strict={false}
                        />
                      </InputVertical>
                    </>
                  )}
                </Section>
              </Modal.Body>
              <Modal.Footer>
                <Button prominence="secondary" onClick={onClose}>
                  取消
                </Button>
                <Button
                  type="submit"
                  disabled={isSubmitting || !isValid || !dirty}
                  icon={isSubmitting ? SvgSimpleLoader : undefined}
                >
                  {isEditing ? "更新" : "连接"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// VoiceDisconnectModal
// ---------------------------------------------------------------------------

interface VoiceDisconnectModalProps {
  disconnectTarget: {
    providerId: number;
    providerLabel: string;
    providerType: string;
  };
  hasAlternatives: boolean;
  onSuccess: () => void;
}

export function VoiceDisconnectModal({
  disconnectTarget,
  hasAlternatives,
  onSuccess,
}: VoiceDisconnectModalProps) {
  const onClose = useModalClose();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleDisconnect() {
    setIsSubmitting(true);
    try {
      const res = await deleteVoiceProvider(disconnectTarget.providerId);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          typeof body?.detail === "string"
            ? body.detail
            : "断开服务商失败。"
        );
      }
      toast.success(`${disconnectTarget.providerLabel} 已断开`);
      onSuccess();
      onClose?.();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "发生未知错误。"
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <ConfirmationModalLayout
      icon={SvgUnplug}
      title={`断开 ${disconnectTarget.providerLabel}`}
      description="这会移除此服务商已保存的凭据。"
      submit={
        <Button
          variant="danger"
          onClick={() => void handleDisconnect()}
          disabled={isSubmitting}
        >
          断开连接
        </Button>
      }
    >
      <Section alignItems="start" gap={0.5}>
        <Text color="text-03">
          {markdown(
            `**${disconnectTarget.providerLabel}** 模型将不再用于语音转文本或文本转语音，也不会再作为默认服务商。会话历史会保留。`
          )}
        </Text>
        {!hasAlternatives && (
          <Text color="text-03">
            请连接另一个服务商以继续使用语音功能。
          </Text>
        )}
      </Section>
    </ConfirmationModalLayout>
  );
}
