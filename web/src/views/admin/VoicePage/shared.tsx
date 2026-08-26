"use client";

import { markdown } from "@opal/utils";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { SvgOnyxLogo } from "@opal/logos";
import { Modal } from "@opal/components";
import { ConfirmationModalLayout } from "@opal/layouts";
import InputComboBoxField from "@/refresh-components/form/InputComboBoxField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { InputVertical, toast } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { SvgArrowExchange, SvgUnplug, SvgSimpleLoader } from "@opal/icons";
import { Button, Text } from "@opal/components";
import { useModalClose } from "@opal/components";
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
  parseSttLanguages,
  sttLanguagesToInput,
  maxSttLanguagesForTargetUri,
  MAX_STT_LANGUAGES,
  STT_LOCALE_PATTERN,
  type ProviderMode,
} from "@/lib/voice/utils";

export { type ProviderMode } from "@/lib/voice/utils";

const AZURE_PORTAL_URL = "https://portal.azure.com/";

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
  const t = useTranslations("admin.voice");
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
    api_key: Yup.string().required(t("setupModal.apiKey.required")),
    target_uri:
      providerType === "azure"
        ? Yup.string().required(t("setupModal.targetUri.required"))
        : Yup.string(),
    stt_model: Yup.string(),
    tts_model: Yup.string(),
    default_voice: Yup.string(),
    stt_languages:
      mode === "stt" && detail.sttLanguages
        ? Yup.string().test(
            "locales",
            t("setupModal.sttLanguages.invalid"),
            (value, context) => {
              if (!value) return true;
              const languages = parseSttLanguages(value);
              const bases = languages.map((lang) =>
                lang.split("-")[0]!.toLowerCase()
              );
              if (
                new Set(bases).size !== bases.length ||
                !languages.every((lang) => STT_LOCALE_PATTERN.test(lang))
              ) {
                return false;
              }
              const cap = maxSttLanguagesForTargetUri(
                context.parent.target_uri ?? ""
              );
              if (languages.length > cap) {
                return context.createError({
                  message:
                    cap === MAX_STT_LANGUAGES
                      ? t("setupModal.sttLanguages.azureCapExceeded", { cap })
                      : t("setupModal.sttLanguages.selfHostedCapExceeded", {
                          cap,
                        }),
                });
              }
              return true;
            }
          )
        : Yup.string(),
  });

  const initialValues: VoiceFormValues = {
    api_key: existingProvider?.api_key ?? "",
    target_uri: existingProvider?.target_uri ?? "",
    stt_model: existingProvider?.stt_model ?? "whisper-1",
    tts_model: initialTtsModel,
    default_voice: initialDefaultVoice,
    stt_languages: sttLanguagesToInput(
      existingProvider?.custom_config?.stt_languages
    ),
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
              : t("setupModal.connectionTestFailed.message")
          );
          setSubmitting(false);
          return;
        }
      }

      // Preserve config keys the form doesn't own (e.g. speech_region).
      const customConfig: Record<string, unknown> = {
        ...existingProvider?.custom_config,
      };
      if (mode === "stt" && detail.sttLanguages) {
        const languages = parseSttLanguages(values.stt_languages);
        if (languages.length > 0) {
          customConfig.stt_languages = languages;
        } else {
          delete customConfig.stt_languages;
        }
      }

      const response = await upsertVoiceProvider({
        id: existingProvider?.id,
        name: detail.label,
        provider_type: providerType,
        api_key: apiKeyChanged ? values.api_key : undefined,
        api_key_changed: apiKeyChanged,
        target_uri: values.target_uri || undefined,
        custom_config: customConfig,
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
            : t("setupModal.saveError.message")
        );
      }
    } catch {
      toast.error(t("setupModal.saveError.message"));
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
                moreIcon2={SvgOnyxLogo}
                title={
                  isEditing
                    ? t("setupModal.editHeader.title", {
                        provider: detail.label,
                      })
                    : t("setupModal.createHeader.title", {
                        provider: detail.label,
                      })
                }
                description={t("setupModal.header.description", {
                  provider: detail.label,
                })}
                onClose={onClose}
              />
              <Modal.Body>
                <Section gap={4} alignItems="stretch">
                  {providerType === "azure" && (
                    <InputVertical
                      title={t("setupModal.targetUri.label")}
                      subDescription={markdown(
                        t("setupModal.targetUri.description", {
                          portalUrl: AZURE_PORTAL_URL,
                        })
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
                    title={t("setupModal.apiKey.label")}
                    subDescription={markdown(
                      t("setupModal.apiKey.description", {
                        url: detail.apiKeyUrl ?? "",
                        provider: detail.label,
                      })
                    )}
                    withLabel="api_key"
                  >
                    <PasswordInputTypeInField
                      name="api_key"
                      placeholder={t("setupModal.apiKey.placeholder")}
                    />
                  </InputVertical>

                  {mode === "stt" && detail.sttLanguages && (
                    <InputVertical
                      title={t("setupModal.sttLanguages.label")}
                      subDescription={markdown(
                        t("setupModal.sttLanguages.description", {
                          docsUrl: detail.sttLanguages.docsUrl,
                        })
                      )}
                      withLabel="stt_languages"
                    >
                      <InputTypeInField
                        name="stt_languages"
                        // oxlint-disable-next-line i18n/no-raw-jsx-text -- locale-code example, not copy
                        placeholder="en-US, fr-FR"
                      />
                    </InputVertical>
                  )}

                  {mode === "stt" && (detail.sttModels?.length ?? 0) > 1 && (
                    <InputVertical
                      title={t("setupModal.sttModel.label")}
                      withLabel="stt_model"
                    >
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
                          title={t("setupModal.ttsModel.label")}
                          subDescription={t("setupModal.ttsModel.description")}
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
                        title={t("setupModal.voice.label")}
                        subDescription={markdown(
                          t("setupModal.voice.description", {
                            docsLabel:
                              detail.voiceDocsUrl?.label ?? detail.label,
                            docsUrl:
                              detail.voiceDocsUrl?.url ?? detail.docsUrl ?? "",
                          })
                        )}
                        withLabel="default_voice"
                      >
                        <InputComboBoxField
                          name="default_voice"
                          options={voiceOptions}
                          placeholder={
                            isLoadingVoices
                              ? t("setupModal.voice.loadingPlaceholder")
                              : t("setupModal.voice.placeholder")
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
                  {t("setupModal.cancelButton.label")}
                </Button>
                <Button
                  type="submit"
                  disabled={isSubmitting || !isValid || !dirty}
                  icon={isSubmitting ? SvgSimpleLoader : undefined}
                >
                  {isEditing
                    ? t("setupModal.updateButton.label")
                    : t("setupModal.connectButton.label")}
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
  const t = useTranslations("admin.voice");
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
            : t("disconnectModal.disconnectError.message")
        );
      }
      toast.success(
        t("disconnectModal.disconnectSuccess.message", {
          label: disconnectTarget.providerLabel,
        })
      );
      onSuccess();
      onClose?.();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("unexpectedError.message")
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <ConfirmationModalLayout
      icon={SvgUnplug}
      title={t("disconnectModal.header.title", {
        label: disconnectTarget.providerLabel,
      })}
      description={t("disconnectModal.header.description")}
      submit={
        <Button
          variant="danger"
          onClick={() => void handleDisconnect()}
          disabled={isSubmitting}
        >
          {t("disconnectModal.submitButton.label")}
        </Button>
      }
    >
      <Section alignItems="start" gap={2}>
        <Text color="text-03">
          {markdown(
            t("disconnectModal.body.description", {
              label: disconnectTarget.providerLabel,
            })
          )}
        </Text>
        {!hasAlternatives && (
          <Text color="text-03">
            {t("disconnectModal.connectAnother.description")}
          </Text>
        )}
      </Section>
    </ConfirmationModalLayout>
  );
}
