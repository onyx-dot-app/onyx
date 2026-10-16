"use client";

import { IconLoader } from "@opal/loaders";
import { useTranslations } from "next-intl";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { SvgArrowExchange } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import { Button } from "@opal/components";
import { Modal } from "@opal/components";
import { useModalClose } from "@opal/components";
import { toast } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { ApiTokenField } from "@/lib/api-tokens/components";
import type { ApiTokenValue } from "@/lib/api-tokens/types";
import {
  initialApiTokenValue,
  toApiTokenPayload,
} from "@/lib/api-tokens/utils";
import { apiTokenSchema } from "@/lib/api-tokens/validation";
import { connectTracingProvider } from "@/lib/tracing/svc";
import type { TracingProviderDetail } from "@/lib/tracing/utils";
import type {
  TracingProviderType,
  TracingProviderView,
} from "@/lib/tracing/types";
import { ConfigField } from "@/views/admin/TracingPage/shared";

export interface TracingSetupModalState {
  providerType: TracingProviderType;
  detail: TracingProviderDetail;
  provider: TracingProviderView | null;
}

export interface TracingSetupModalProps {
  state: TracingSetupModalState;
  onSaved: () => Promise<void>;
}

interface FormValues {
  api_key: ApiTokenValue;
  config: Record<string, string>;
}

export function TracingSetupModal({ state, onSaved }: TracingSetupModalProps) {
  const t = useTranslations("admin.tracing");
  const onClose = useModalClose();
  const { providerType, detail, provider } = state;

  // Only a DB-backed provider has a saved key. An env-sourced provider has
  // no retrievable key, so the admin must enter one (which adopts it into the
  // DB).
  const savedProvider = provider?.source === "db" ? provider : null;
  const isEditing = !!provider?.connected;

  const initialConfig: Record<string, string> = {};
  for (const field of detail.configFields) {
    initialConfig[field.name] =
      provider?.config?.[field.name] ?? field.defaultValue ?? "";
  }
  const initialValues: FormValues = {
    api_key: initialApiTokenValue(savedProvider?.api_token_id),
    config: initialConfig,
  };

  const configShape: Record<string, Yup.StringSchema> = {};
  for (const field of detail.configFields) {
    configShape[field.name] = field.optional
      ? Yup.string()
      : Yup.string().required(
          t("field.required.error", { label: t(field.labelKey) })
        );
  }
  const validationSchema = Yup.object().shape({
    api_key: apiTokenSchema(
      t("field.required.error", { label: t(detail.secretField.labelKey) })
    ),
    config: Yup.object().shape(configShape),
  });

  async function handleSubmit(
    values: FormValues,
    { setSubmitting }: { setSubmitting: (v: boolean) => void }
  ) {
    const config: Record<string, string> = {};
    for (const field of detail.configFields) {
      const value = (values.config[field.name] ?? "").trim();
      if (value) config[field.name] = value;
    }

    try {
      await connectTracingProvider({
        providerType,
        apiKey: toApiTokenPayload(values.api_key),
        config,
      });
      toast.success(t("toasts.connected", { label: detail.label }));
      await onSaved();
      onClose?.();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("toasts.unexpectedError")
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="sm" preventAccidentalClose>
        <Formik
          initialValues={initialValues}
          validationSchema={validationSchema}
          onSubmit={handleSubmit}
        >
          {({ isSubmitting, dirty, isValid }) => (
            <Form>
              <Modal.Header
                icon={detail.logo}
                moreIcon1={SvgArrowExchange}
                moreIcon2={SvgOnyxLogo}
                title={
                  isEditing
                    ? t("setupModal.editTitle", { label: detail.label })
                    : t("setupModal.createTitle", { label: detail.label })
                }
                description={t("setupModal.description", {
                  label: detail.label,
                })}
                onClose={onClose}
              />
              <Modal.Body>
                <ApiTokenField
                  platform={providerType}
                  savedMaskedValue={savedProvider?.masked_api_key ?? undefined}
                  subDescription={
                    detail.secretField.descriptionKey
                      ? markdown(t(detail.secretField.descriptionKey))
                      : undefined
                  }
                />
                {detail.configFields.map((field) => (
                  <ConfigField
                    key={field.name}
                    field={field}
                    name={`config.${field.name}`}
                  />
                ))}
              </Modal.Body>
              <Modal.Footer>
                <Button prominence="secondary" type="button" onClick={onClose}>
                  {t("setupModal.cancel.label")}
                </Button>
                <Button
                  type="submit"
                  disabled={!dirty || !isValid || isSubmitting}
                  icon={isSubmitting ? IconLoader : undefined}
                >
                  {isEditing
                    ? t("setupModal.update.label")
                    : t("setupModal.connect.label")}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
