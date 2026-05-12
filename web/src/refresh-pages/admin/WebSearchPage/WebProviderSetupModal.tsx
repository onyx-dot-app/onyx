"use client";

import { Formik, Form } from "formik";
import * as Yup from "yup";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { SvgArrowExchange } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import { Button } from "@opal/components";
import Modal from "@/refresh-components/Modal";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import {
  buildSearchProviderConfig,
  buildContentProviderConfig,
} from "@/lib/webSearch/utils";

import { connectProviderFlow } from "@/lib/webSearch/svc";
import type { WebProviderCategory } from "@/lib/webSearch/types";
import {
  ApiKeyField,
  ConfigTextField,
} from "@/refresh-pages/admin/WebSearchPage/shared";

export interface ExistingProviderInfo {
  id: number;
  name: string;
  has_api_key: boolean;
}

export interface ConfigFieldSpec {
  title: string;
  placeholder: string;
  subDescription?: string | RichStr;
}

export interface WebProviderSetupModalProps {
  providerType: string;
  category: WebProviderCategory;
  providerLabel: string;
  icon?: IconFunctionComponent;
  apiKeyUrl?: string;
  existingProvider?: ExistingProviderInfo | null;
  /**
   * When true, an API key is already available via a sibling provider (e.g. Exa
   * search key shared with Exa content). Skips the required-key validation and
   * renders the API key field in non-revealable mode.
   */
  hasSharedApiKey?: boolean;
  initialConfigValue?: string;
  requiresApiKey: boolean;
  configField?: ConfigFieldSpec;
  mutate: () => Promise<unknown>;
  onSuccess: () => void;
}

interface FormValues {
  api_key: string;
  config: string;
}

export function WebProviderSetupModal({
  providerType,
  category,
  providerLabel,
  icon,
  apiKeyUrl,
  existingProvider,
  hasSharedApiKey = false,
  initialConfigValue,
  requiresApiKey,
  configField,
  mutate,
  onSuccess,
}: WebProviderSetupModalProps) {
  const onClose = useModalClose();
  const isEditing = !!existingProvider && existingProvider.id > 0;

  const hasStoredKey =
    (existingProvider?.has_api_key ?? false) || hasSharedApiKey;
  const initialConfig = initialConfigValue ?? "";

  const initialValues: FormValues = {
    api_key: "",
    config: initialConfig,
  };

  const validationSchema = Yup.object().shape({
    api_key:
      requiresApiKey && !hasStoredKey
        ? Yup.string().required("API key is required")
        : Yup.string(),
    config: configField
      ? Yup.string().required(`${configField.title} is required`)
      : Yup.string(),
  });

  async function handleSubmit(
    values: FormValues,
    { setSubmitting }: { setSubmitting: (v: boolean) => void }
  ) {
    const apiKeyChanged = requiresApiKey && values.api_key.trim().length > 0;

    const config =
      category === "search"
        ? buildSearchProviderConfig(providerType, values.config)
        : buildContentProviderConfig(providerType, values.config);

    const configChanged = values.config !== initialConfig;

    try {
      await connectProviderFlow({
        category,
        providerType,
        existingProviderId: existingProvider?.id ?? null,
        existingProviderName: existingProvider?.name ?? null,
        existingProviderHasApiKey:
          (existingProvider?.has_api_key ?? false) || hasSharedApiKey,
        displayName: providerLabel,
        providerRequiresApiKey: requiresApiKey,
        apiKeyChangedForProvider: apiKeyChanged,
        apiKey: values.api_key,
        config,
        configChanged,
        onValidating: () => {},
        onSaving: () => {},
        onError: (message) => toast.error(message),
        onClose: onSuccess,
        mutate,
      });
    } finally {
      setSubmitting(false);
    }
  }

  const hasNoFields = !requiresApiKey && !configField;

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
                icon={icon}
                moreIcon1={SvgArrowExchange}
                moreIcon2={SvgOnyxLogo}
                title={
                  isEditing
                    ? `Configure ${providerLabel}`
                    : `Set up ${providerLabel}`
                }
                onClose={onClose}
              />
              {!hasNoFields && (
                <Modal.Body>
                  {requiresApiKey && (
                    <ApiKeyField
                      providerLabel={providerLabel}
                      apiKeyUrl={apiKeyUrl}
                      isNonRevealable={hasStoredKey}
                    />
                  )}
                  {configField && (
                    <ConfigTextField
                      title={configField.title}
                      placeholder={configField.placeholder}
                      subDescription={configField.subDescription}
                    />
                  )}
                </Modal.Body>
              )}
              <Modal.Footer>
                <Button prominence="secondary" type="button" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={
                    (!hasNoFields && (!dirty || !isValid)) || isSubmitting
                  }
                  icon={isSubmitting ? SimpleLoader : undefined}
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
