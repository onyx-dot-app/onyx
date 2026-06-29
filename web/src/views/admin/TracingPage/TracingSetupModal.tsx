"use client";

import { Formik, Form } from "formik";
import * as Yup from "yup";
import { SvgArrowExchange, SvgBarChart, SvgSimpleLoader } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import { Button } from "@opal/components";
import Modal from "@/refresh-components/Modal";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import { connectTracingProvider } from "@/lib/tracing/svc";
import type { TracingProviderMeta } from "@/lib/tracing/constants";
import type { TracingProviderView } from "@/lib/tracing/types";
import { SecretField, ConfigField } from "@/views/admin/TracingPage/shared";

export interface TracingSetupModalState {
  meta: TracingProviderMeta;
  provider: TracingProviderView | null;
}

export interface TracingSetupModalProps {
  state: TracingSetupModalState;
  onSaved: () => Promise<unknown>;
}

type FormValues = Record<string, string>;

export function TracingSetupModal({ state, onSaved }: TracingSetupModalProps) {
  const onClose = useModalClose();
  const { meta, provider } = state;

  // Only a DB-backed provider exposes a stored (masked) key. An env-sourced
  // provider has no retrievable key, so the admin must enter one (which adopts
  // it into the DB).
  const hasStoredKey = provider?.source === "db" && !!provider.masked_api_key;
  const isEditing = !!provider?.connected;

  const initialApiKey = hasStoredKey ? (provider?.masked_api_key ?? "") : "";

  const initialValues: FormValues = {
    [meta.secretField.name]: initialApiKey,
  };
  for (const field of meta.configFields) {
    initialValues[field.name] =
      provider?.config?.[field.name] ?? field.defaultValue ?? "";
  }

  const shape: Record<string, Yup.StringSchema> = {
    [meta.secretField.name]: hasStoredKey
      ? Yup.string()
      : Yup.string().required(`${meta.secretField.label} is required`),
  };
  for (const field of meta.configFields) {
    shape[field.name] = field.optional
      ? Yup.string()
      : Yup.string().required(`${field.label} is required`);
  }
  const validationSchema = Yup.object().shape(shape);

  async function handleSubmit(
    values: FormValues,
    { setSubmitting }: { setSubmitting: (v: boolean) => void }
  ) {
    const apiKey = values[meta.secretField.name] ?? "";
    const apiKeyChanged = apiKey !== initialApiKey;

    const config: Record<string, string> = {};
    for (const field of meta.configFields) {
      const value = (values[field.name] ?? "").trim();
      if (value) config[field.name] = value;
    }

    try {
      await connectTracingProvider({
        providerType: meta.type,
        apiKey,
        apiKeyChanged,
        hasStoredKey,
        config,
      });
      toast.success(`${meta.label} connected`);
      await onSaved();
      onClose?.();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Unexpected error occurred."
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
          {({ isSubmitting, isValid }) => (
            <Form>
              <Modal.Header
                icon={SvgBarChart}
                moreIcon1={SvgArrowExchange}
                moreIcon2={SvgOnyxLogo}
                title={
                  isEditing ? `Configure ${meta.label}` : `Set up ${meta.label}`
                }
                description={`Connect to ${meta.label} to send LLM call traces.`}
                onClose={onClose}
              />
              <Modal.Body>
                <SecretField field={meta.secretField} />
                {meta.configFields.map((field) => (
                  <ConfigField key={field.name} field={field} />
                ))}
              </Modal.Body>
              <Modal.Footer>
                <Button prominence="secondary" type="button" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={!isValid || isSubmitting}
                  icon={isSubmitting ? SvgSimpleLoader : undefined}
                >
                  {isEditing ? "Update" : "Connect"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
