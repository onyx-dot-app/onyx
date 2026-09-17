"use client";

import { Formik, useFormikContext } from "formik";
import { useTranslations } from "next-intl";
import * as Yup from "yup";
import { Button } from "@opal/components";
import { SvgArrowExchange, SvgSimpleLoader } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { Modal } from "@opal/components";
import { toast } from "@opal/layouts";
import {
  EmbeddingModelRequest,
  EmbeddingProviderName,
  type ConfiguredEmbeddingProvider,
  type EmbeddingModel,
  type EmbeddingProvider,
} from "@/lib/indexing/types";
import { connectEmbeddingProvider, testEmbedding } from "@/lib/indexing/svc";
import {
  ApiKeyField,
  ApiUrlField,
  GoogleCredentialsField,
  ModelSpecFields,
  TextField,
  modelSpecSchemaShape,
} from "@/views/admin/IndexSettingsPage/shared";
import { useModalClose } from "@opal/components";

// ---------------------------------------------------------------------------
// Shared modal shell — reads `isValid`, `isSubmitting`, `submitForm` from the
// surrounding Formik context. Every modal in this file is wrapped in a
// `<Formik>` whose schema enforces field-level validation and whose
// `onSubmit` toasts backend errors instead of showing inline cards.
// ---------------------------------------------------------------------------

interface ModalShellProps {
  provider: EmbeddingProvider;
  isEditing: boolean;
  children: React.ReactNode;
}

function ModalShell({ provider, isEditing, children }: ModalShellProps) {
  const t = useTranslations("admin.indexSettings");
  const { isValid, isSubmitting, submitForm, dirty } = useFormikContext();
  const onClose = useModalClose();

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="md">
        <Modal.Header
          icon={provider.icon}
          moreIcon1={SvgArrowExchange}
          moreIcon2={SvgOnyxLogo}
          title={
            isEditing
              ? t("modal.manage.title", { provider: provider.displayName })
              : t("modal.setUp.title", { provider: provider.displayName })
          }
          description={
            isEditing
              ? t("modal.manage.description", {
                  provider: provider.displayName,
                })
              : t("modal.setUp.description", { provider: provider.displayName })
          }
          onClose={onClose}
        />
        <Modal.Body twoTone>
          <GeneralLayouts.Section gap={4}>{children}</GeneralLayouts.Section>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            {t("modal.cancelButton.label")}
          </Button>
          <Button
            disabled={!isValid || !dirty || isSubmitting}
            onClick={submitForm}
            icon={isSubmitting ? SvgSimpleLoader : undefined}
          >
            {isEditing
              ? t("modal.updateButton.label")
              : t("modal.connectButton.label")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Tests credentials against the backend then persists them if the test passes.
// Returns `true` on success so callers can chain their own follow-up
// (e.g. staging a freshly-defined LiteLLM model). On failure, toasts the
// error and returns `false`.
//
// `apiUrl`, `apiVersion`, `deploymentName` default to "" / null so simple
// providers (OpenAI / Cohere / Voyage / Google) only have to pass `apiKey`.
// ---------------------------------------------------------------------------

async function testAndSaveProviderCredentials({
  provider,
  apiKey,
  unknownErrorMessage,
  apiUrl = "",
  modelName = "",
  apiVersion = null,
  deploymentName = null,
}: {
  provider: EmbeddingProvider;
  apiKey: string | null;
  /** Fallback toast copy when the backend error carries no message. */
  unknownErrorMessage: string;
  apiUrl?: string;
  modelName?: string;
  apiVersion?: string | null;
  deploymentName?: string | null;
}): Promise<boolean> {
  try {
    await connectEmbeddingProvider({
      providerType: provider.providerName,
      apiKey,
      apiUrl,
      modelName,
      apiVersion,
      deploymentName,
    });
    return true;
  } catch (error: unknown) {
    toast.error(error instanceof Error ? error.message : unknownErrorMessage);
    return false;
  }
}

// ---------------------------------------------------------------------------
// Shared props
// ---------------------------------------------------------------------------

interface ProviderModalProps {
  provider: EmbeddingProvider;
  existingCredentials?: ConfiguredEmbeddingProvider;
  /**
   * Current model spec for THIS provider, when the active embedding model
   * belongs to it. `LiteLLMProviderModal` and `CustomSelfHostedModal` use
   * this to preload model-spec fields (modelName, modelDim, prefixes,
   * normalize) so the user doesn't have to retype them when editing.
   */
  existingModel?: EmbeddingModel;
  /**
   * Called after the modal finishes its work. The optional `customModel`
   * argument is only populated by `CustomSelfHostedModal`, which uses it
   * to hand the just-defined model spec back to the page so it can be
   * staged into the Formik form.
   */
  onSubmit: (req?: EmbeddingModelRequest) => void;
}

// ---------------------------------------------------------------------------
// Standard provider modal (OpenAI, Cohere, Voyage)
// ---------------------------------------------------------------------------

interface StandardFormValues {
  apiKey: string;
}
function StandardProviderModal({
  provider,
  existingCredentials,
  onSubmit,
}: ProviderModalProps) {
  const t = useTranslations("admin.indexSettings");
  const isEditing = !!existingCredentials;
  const maskedApiKey = existingCredentials?.api_key ?? "";

  const schema = Yup.object({
    apiKey: isEditing
      ? Yup.string().trim()
      : Yup.string().trim().required(t("validation.apiKeyRequired")),
  });

  const initialValues: StandardFormValues = { apiKey: maskedApiKey };

  return (
    <Formik<StandardFormValues>
      initialValues={initialValues}
      validationSchema={schema}
      validateOnMount
      onSubmit={async (values) => {
        const apiKey =
          values.apiKey === maskedApiKey ? null : values.apiKey || null;
        if (
          await testAndSaveProviderCredentials({
            provider,
            apiKey,
            unknownErrorMessage: t("toasts.unknownError"),
          })
        ) {
          onSubmit();
        }
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing}>
        <ApiKeyField provider={provider} />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// Google
// ---------------------------------------------------------------------------

interface GoogleFormValues {
  apiKey: string;
}
function GoogleProviderModal({
  provider,
  existingCredentials,
  onSubmit,
}: ProviderModalProps) {
  const t = useTranslations("admin.indexSettings");
  const isEditing = !!existingCredentials;

  const schema = Yup.object({
    apiKey: isEditing
      ? Yup.string()
      : Yup.string()
          .required(t("validation.serviceAccountJsonRequired"))
          .test(
            "service-account-json",
            t("validation.serviceAccountJsonInvalid"),
            (value) => {
              if (!value) return false;
              try {
                const parsed = JSON.parse(value);
                return (
                  parsed.type === "service_account" &&
                  typeof parsed.client_email === "string" &&
                  typeof parsed.private_key === "string"
                );
              } catch {
                return false;
              }
            }
          ),
  });

  const initialValues: GoogleFormValues = { apiKey: "" };

  return (
    <Formik<GoogleFormValues>
      initialValues={initialValues}
      validationSchema={schema}
      validateOnMount
      onSubmit={async (values) => {
        if (
          await testAndSaveProviderCredentials({
            provider,
            apiKey: values.apiKey || null,
            unknownErrorMessage: t("toasts.unknownError"),
          })
        ) {
          onSubmit();
        }
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing}>
        <GoogleCredentialsField />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// Azure
// ---------------------------------------------------------------------------

interface AzureFormValues {
  apiUrl: string;
  apiKey: string;
  apiVersion: string;
  deploymentName: string;
  modelName: string;
  modelDim: number;
  queryPrefix: string;
  passagePrefix: string;
  normalize: boolean;
}
function AzureProviderModal({
  provider,
  existingCredentials,
  existingModel,
  onSubmit,
}: ProviderModalProps) {
  const t = useTranslations("admin.indexSettings");
  const isEditing = !!existingCredentials;
  const maskedApiKey = existingCredentials?.api_key ?? "";

  const schema = Yup.object({
    apiUrl: Yup.string()
      .trim()
      .required(t("validation.targetUrlRequired"))
      .url(t("validation.urlInvalid")),
    apiKey: isEditing
      ? Yup.string().trim()
      : Yup.string().trim().required(t("validation.apiKeyRequired")),
    apiVersion: Yup.string()
      .trim()
      .required(t("validation.apiVersionRequired")),
    deploymentName: Yup.string()
      .trim()
      .required(t("validation.deploymentNameRequired")),
    ...modelSpecSchemaShape(t),
  });

  const initialValues: AzureFormValues = {
    apiUrl: existingCredentials?.api_url ?? "",
    apiKey: maskedApiKey,
    apiVersion: existingCredentials?.api_version ?? "",
    deploymentName: existingCredentials?.deployment_name ?? "",
    modelName: existingModel?.modelName ?? "",
    modelDim: existingModel?.modelDim ?? 0,
    queryPrefix: existingModel?.queryPrefix ?? "",
    passagePrefix: existingModel?.passagePrefix ?? "",
    normalize: existingModel?.normalize ?? false,
  };

  return (
    <Formik<AzureFormValues>
      initialValues={initialValues}
      validationSchema={schema}
      validateOnMount
      onSubmit={async (values) => {
        const apiKey =
          values.apiKey === maskedApiKey ? null : values.apiKey || null;
        if (
          await testAndSaveProviderCredentials({
            provider,
            apiKey,
            unknownErrorMessage: t("toasts.unknownError"),
            apiUrl: values.apiUrl,
            apiVersion: values.apiVersion,
            deploymentName: values.deploymentName,
          })
        ) {
          onSubmit({
            modelName: values.modelName.trim(),
            modelDim: values.modelDim,
            normalize: values.normalize,
            queryPrefix: values.queryPrefix || null,
            passagePrefix: values.passagePrefix || null,
          });
        }
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing}>
        <ApiUrlField
          title={t("azure.targetUrl.title")}
          placeholder="https://your_resource_name.openai.azure.com/openai/v1/embeddings"
        />
        <ApiKeyField provider={provider} />
        <TextField
          name="apiVersion"
          title={t("azure.apiVersion.title")}
          placeholder={t("azure.apiVersion.placeholder")}
          subDescription={t("azure.apiVersion.description")}
        />
        <TextField
          name="deploymentName"
          title={t("azure.deploymentName.title")}
          placeholder={t("azure.deploymentName.placeholder")}
          subDescription={t("azure.deploymentName.description")}
        />

        <ModelSpecFields
          modelNameSubDescription={t("azure.modelName.description")}
        />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// LiteLLM
// ---------------------------------------------------------------------------

interface LiteLLMFormValues {
  apiUrl: string;
  apiKey: string;
  modelName: string;
  modelDim: number;
  queryPrefix: string;
  passagePrefix: string;
  normalize: boolean;
}
function LiteLLMProviderModal({
  provider,
  existingCredentials,
  existingModel,
  onSubmit,
}: ProviderModalProps) {
  const t = useTranslations("admin.indexSettings");
  const isEditing = !!existingCredentials;
  const maskedApiKey = existingCredentials?.api_key ?? "";

  const schema = Yup.object({
    apiUrl: Yup.string()
      .trim()
      .required(t("validation.apiBaseUrlRequired"))
      .url(t("validation.urlInvalid")),
    apiKey: isEditing
      ? Yup.string().trim()
      : Yup.string().trim().required(t("validation.apiKeyRequired")),
    ...modelSpecSchemaShape(t),
  });

  const initialValues: LiteLLMFormValues = {
    apiUrl: existingCredentials?.api_url ?? "",
    apiKey: maskedApiKey,
    modelName: existingModel?.modelName ?? "",
    modelDim: existingModel?.modelDim ?? 0,
    queryPrefix: existingModel?.queryPrefix ?? "",
    passagePrefix: existingModel?.passagePrefix ?? "",
    normalize: existingModel?.normalize ?? false,
  };

  return (
    <Formik<LiteLLMFormValues>
      initialValues={initialValues}
      validationSchema={schema}
      validateOnMount
      onSubmit={async (values) => {
        const apiKey =
          values.apiKey === maskedApiKey ? null : values.apiKey || null;
        if (
          await testAndSaveProviderCredentials({
            provider,
            apiKey,
            apiUrl: values.apiUrl,
            modelName: values.modelName.trim(),
            unknownErrorMessage: t("toasts.unknownError"),
          })
        ) {
          onSubmit({
            modelName: values.modelName.trim(),
            modelDim: values.modelDim,
            normalize: values.normalize,
            queryPrefix: values.queryPrefix || null,
            passagePrefix: values.passagePrefix || null,
          });
        }
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing}>
        <ApiUrlField
          title={t("litellm.apiUrl.title")}
          placeholder="https://..."
          subDescription={t("litellm.apiUrl.description", {
            provider: provider.displayName,
          })}
        />

        <ApiKeyField provider={provider} />

        <ModelSpecFields
          modelNameSubDescription={t("litellm.modelName.description", {
            provider: provider.displayName,
          })}
        />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// Custom Self-Hosted
// ---------------------------------------------------------------------------

function CustomSelfHostedModal({
  provider,
  existingModel,
  onSubmit,
}: ProviderModalProps) {
  const t = useTranslations("admin.indexSettings");
  const isEditing = !!existingModel;
  const customSchema = Yup.object(modelSpecSchemaShape(t));

  const initialValues: EmbeddingModelRequest = {
    modelName: existingModel?.modelName,
    modelDim: existingModel?.modelDim ?? null,
    queryPrefix: existingModel?.queryPrefix,
    passagePrefix: existingModel?.passagePrefix,
    normalize: existingModel?.normalize ?? false,
  };

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={customSchema}
      validateOnMount
      onSubmit={(values) => {
        onSubmit({
          modelName: values.modelName?.trim(),
          modelDim: values.modelDim,
          normalize: values.normalize,
          queryPrefix: values.queryPrefix || null,
          passagePrefix: values.passagePrefix || null,
        });
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing}>
        <ModelSpecFields />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// Provider credentials modal (connect + edit)
// ---------------------------------------------------------------------------

export function ProviderCredentialsModal(props: ProviderModalProps) {
  switch (props.provider.providerName) {
    case EmbeddingProviderName.GOOGLE:
      return <GoogleProviderModal {...props} />;
    case EmbeddingProviderName.AZURE:
      return <AzureProviderModal {...props} />;
    case EmbeddingProviderName.LITELLM:
      return <LiteLLMProviderModal {...props} />;
    case EmbeddingProviderName.CUSTOM:
      return <CustomSelfHostedModal {...props} />;
    default:
      return <StandardProviderModal {...props} />;
  }
}
