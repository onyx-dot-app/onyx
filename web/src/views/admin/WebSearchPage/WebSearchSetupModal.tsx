"use client";

import { IconLoader } from "@opal/loaders";
import { Formik, Form } from "formik";
import { useTranslations } from "next-intl";
import * as Yup from "yup";
import { markdown } from "@opal/utils";
import { SvgArrowExchange } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import { Button } from "@opal/components";
import { Modal } from "@opal/components";
import { useModalClose } from "@opal/components";
import { toast } from "@opal/layouts";
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
import { ApiTokenField } from "@/lib/api-tokens/components";
import type { ApiTokenValue } from "@/lib/api-tokens/types";
import {
  initialApiTokenValue,
  toApiTokenPayload,
} from "@/lib/api-tokens/utils";
import { apiTokenSchema } from "@/lib/api-tokens/validation";
import type {
  WebSearchProviderType,
  WebSearchProviderView,
  WebContentProviderView,
} from "@/lib/webSearch/types";
import { ConfigTextField } from "@/views/admin/WebSearchPage/shared";

interface FormValues {
  api_key: ApiTokenValue;
  config: string;
}

function isSameApiTokenValue(a: ApiTokenValue, b: ApiTokenValue): boolean {
  if (a.type === "existing" && b.type === "existing") return a.id === b.id;
  if (a.type === "new" && b.type === "new") return a.value === b.value;
  return false;
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

export interface WebSearchSetupModalProps {
  state: ProviderModalState;
}

export function WebSearchSetupModal({ state }: WebSearchSetupModalProps) {
  const t = useTranslations("admin.webSearch");
  const onClose = useModalClose();
  const { category, providerType, provider } = state;
  const { mutateSearchProviders, mutateContentProviders } =
    useWebSearchProviders();

  const isEditing = !!provider && provider.id > 0;

  const requiresApiKey =
    category === "search"
      ? searchProviderRequiresApiKey(providerType)
      : providerType !== "onyx_web_crawler";

  const configField =
    category === "search"
      ? getSearchConfigField(providerType, t)
      : getContentConfigField(providerType, t);

  const providerLabel =
    category === "search"
      ? getSearchProviderDisplayLabel(providerType, provider?.name)
      : (CONTENT_PROVIDER_DETAILS[providerType]?.label ?? providerType);

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

  // A placeholder provider (id < 0) can carry the key its sibling side uses.
  const initialApiKey = initialApiTokenValue(provider?.api_token_id);
  const prefilledKey = !isEditing && initialApiKey.type === "existing";

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
    api_key: requiresApiKey
      ? apiTokenSchema(t("setupModal.apiKey.required"))
      : apiTokenSchema(),
    config: configField
      ? Yup.string().required(
          t("setupModal.config.required", { title: configField.title })
        )
      : Yup.string(),
  });

  async function mutate() {
    // Providers whose key the backend shares with the other side need both
    // lists refreshed so the sibling card leaves the disconnected state.
    const syncsSiblingSide = ["exa", "tavily", "firecrawl"].includes(
      providerType
    );
    if (category === "search") {
      await mutateSearchProviders();
      if (syncsSiblingSide) await mutateContentProviders();
    } else {
      await mutateContentProviders();
      if (syncsSiblingSide) await mutateSearchProviders();
    }
  }

  async function handleSubmit(
    values: FormValues,
    { setSubmitting }: { setSubmitting: (v: boolean) => void }
  ) {
    const apiKeyChanged =
      requiresApiKey && !isSameApiTokenValue(values.api_key, initialApiKey);

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
        displayName: providerLabel,
        providerRequiresApiKey: requiresApiKey,
        apiKey: requiresApiKey ? toApiTokenPayload(values.api_key) : undefined,
        apiKeyChanged,
        config,
        configChanged,
        onValidating: () => {},
        onSaving: () => {},
        onError: (message) => toast.error(message),
        onClose: () => {
          toast.success(t("setupModal.connectSuccess.message"));
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
                    ? t("setupModal.editHeader.title", {
                        provider: providerLabel,
                      })
                    : t("setupModal.createHeader.title", {
                        provider: providerLabel,
                      })
                }
                onClose={onClose}
              />
              {!hasNoFields && (
                <Modal.Body>
                  {requiresApiKey && (
                    <ApiTokenField
                      platform={providerType}
                      savedMaskedValue={provider?.masked_api_key ?? undefined}
                      subDescription={
                        apiKeyUrl
                          ? markdown(
                              t("apiKeyField.withLink.description", {
                                url: apiKeyUrl,
                                provider: providerLabel,
                              })
                            )
                          : undefined
                      }
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
                  {t("setupModal.cancelButton.label")}
                </Button>
                <Button
                  type="submit"
                  disabled={
                    (!hasNoFields && ((!dirty && !prefilledKey) || !isValid)) ||
                    isSubmitting
                  }
                  icon={isSubmitting ? IconLoader : undefined}
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
