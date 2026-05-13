"use client";

import { Formik, Form } from "formik";
import * as Yup from "yup";
import { SvgArrowExchange } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import { Button } from "@opal/components";
import Modal from "@/refresh-components/Modal";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import { useWebSearchProviders } from "@/lib/webSearch/hooks";
import {
  buildSearchProviderConfig,
  buildContentProviderConfig,
  getSingleConfigFieldValueForForm,
  getSingleContentConfigFieldValueForForm,
  getSearchConfigField,
  getContentConfigField,
  searchProviderRequiresApiKey,
  getSearchProviderDisplayLabel,
  SEARCH_PROVIDER_DETAILS,
  CONTENT_PROVIDER_DETAILS,
} from "@/lib/webSearch/utils";
import { connectProviderFlow } from "@/lib/webSearch/svc";
import type {
  WebSearchProviderType,
  WebSearchProviderView,
  WebContentProviderView,
} from "@/lib/webSearch/types";
import {
  ApiKeyField,
  ConfigTextField,
} from "@/refresh-pages/admin/WebSearchPage/shared";

interface FormValues {
  api_key: string;
  config: string;
}

export type ProviderModalState =
  | {
      category: "search";
      providerType: WebSearchProviderType;
      provider: WebSearchProviderView | null;
    }
  | {
      category: "content";
      providerType: string;
      provider: WebContentProviderView | null;
    };

export interface WebProviderSetupModalProps {
  state: ProviderModalState;
}

export function WebProviderSetupModal({ state }: WebProviderSetupModalProps) {
  const onClose = useModalClose();
  const { category, providerType, provider } = state;
  const {
    searchProviders,
    contentProviders,
    mutateSearchProviders,
    mutateContentProviders,
  } = useWebSearchProviders();

  const exaSibling =
    providerType === "exa"
      ? category === "search"
        ? {
            category: "content" as const,
            existingProviderId:
              contentProviders.find((p) => p.provider_type === "exa")?.id ??
              null,
            existingProviderName:
              contentProviders.find((p) => p.provider_type === "exa")?.name ??
              null,
          }
        : {
            category: "search" as const,
            existingProviderId:
              searchProviders.find((p) => p.provider_type === "exa")?.id ??
              null,
            existingProviderName:
              searchProviders.find((p) => p.provider_type === "exa")?.name ??
              null,
          }
      : undefined;

  const isEditing = !!provider && provider.id > 0;
  const hasStoredKey = !!(
    provider &&
    provider.id > 0 &&
    provider.masked_api_key
  );

  const requiresApiKey =
    category === "search"
      ? searchProviderRequiresApiKey(providerType)
      : providerType !== "onyx_web_crawler";

  const configField =
    category === "search"
      ? getSearchConfigField(providerType)
      : getContentConfigField(providerType);

  const providerLabel =
    category === "search"
      ? getSearchProviderDisplayLabel(providerType, provider?.name)
      : CONTENT_PROVIDER_DETAILS[providerType]?.label ?? providerType;

  const icon =
    category === "search"
      ? SEARCH_PROVIDER_DETAILS[
          providerType as keyof typeof SEARCH_PROVIDER_DETAILS
        ]?.logo
      : CONTENT_PROVIDER_DETAILS[providerType]?.logo;

  const apiKeyUrl =
    category === "search"
      ? SEARCH_PROVIDER_DETAILS[
          providerType as keyof typeof SEARCH_PROVIDER_DETAILS
        ]?.apiKeyUrl
      : undefined;

  const initialApiKey =
    provider && provider.id > 0 ? provider.masked_api_key ?? "" : "";

  const initialConfig = configField
    ? (category === "search"
        ? getSingleConfigFieldValueForForm(providerType, provider)
        : getSingleContentConfigFieldValueForForm(providerType, provider)) ||
      configField.defaultValue ||
      ""
    : "";

  const initialValues: FormValues = {
    api_key: initialApiKey,
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

  async function mutate() {
    if (category === "search") {
      await mutateSearchProviders();
      if (providerType === "exa") await mutateContentProviders();
    } else {
      await mutateContentProviders();
      if (providerType === "exa") await mutateSearchProviders();
    }
  }

  async function handleSubmit(
    values: FormValues,
    { setSubmitting }: { setSubmitting: (v: boolean) => void }
  ) {
    const apiKeyChanged = requiresApiKey && values.api_key !== initialApiKey;

    const config =
      category === "search"
        ? buildSearchProviderConfig(providerType, values.config)
        : buildContentProviderConfig(providerType, values.config);

    const configChanged = values.config !== initialConfig;

    try {
      await connectProviderFlow({
        category,
        providerType,
        existingProviderId: provider && provider.id > 0 ? provider.id : null,
        existingProviderName:
          provider && provider.id > 0 ? provider.name : null,
        existingProviderHasApiKey: hasStoredKey,
        displayName: providerLabel,
        providerRequiresApiKey: requiresApiKey,
        apiKeyChangedForProvider: apiKeyChanged,
        apiKey: values.api_key,
        config,
        configChanged,
        exaSibling,
        onValidating: () => {},
        onSaving: () => {},
        onError: (message) => toast.error(message),
        onClose: () => {
          toast.success("Provider connected");
          onClose?.();
        },
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
