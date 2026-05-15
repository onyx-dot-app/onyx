"use client";

import { Formik, useFormikContext } from "formik";
import * as Yup from "yup";
import { Button } from "@opal/components";
import { SvgArrowExchange } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import * as GeneralLayouts from "@/layouts/general-layouts";
import Modal from "@/refresh-components/Modal";
import { toast } from "@/hooks/useToast";
import {
  EmbeddingModelRequest,
  EmbeddingProviderName,
  type ConfiguredEmbeddingProvider,
  type EmbeddingModel,
  type EmbeddingProvider,
} from "@/lib/indexing/interfaces";
import { connectEmbeddingProvider, testEmbedding } from "@/lib/indexing/svc";
import {
  ApiKeyField,
  ApiUrlField,
  GoogleCredentialsField,
  ModelSpecFields,
  TextField,
  modelSpecSchemaShape,
} from "@/refresh-pages/admin/IndexSettingsPage/shared";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";

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
              ? `Manage ${provider.displayName}`
              : `Set up ${provider.displayName}`
          }
          description={
            isEditing
              ? `Manage ${provider.displayName} provider and model details.`
              : `Connect to ${provider.displayName} and set up your ${provider.displayName} embedding models.`
          }
          onClose={onClose}
        />
        <Modal.Body twoTone>
          <GeneralLayouts.Section gap={1}>{children}</GeneralLayouts.Section>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!isValid || !dirty || isSubmitting}
            onClick={submitForm}
            icon={isSubmitting ? SimpleLoader : undefined}
          >
            {isEditing ? "Update" : "Connect"}
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
  apiUrl = "",
  apiVersion = null,
  deploymentName = null,
}: {
  provider: EmbeddingProvider;
  apiKey: string | null;
  apiUrl?: string;
  apiVersion?: string | null;
  deploymentName?: string | null;
}): Promise<boolean> {
  try {
    await connectEmbeddingProvider({
      providerType: provider.providerName,
      apiKey,
      apiUrl,
      apiVersion,
      deploymentName,
    });
    return true;
  } catch (error: unknown) {
    toast.error(
      error instanceof Error ? error.message : "An unknown error occurred"
    );
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
  const isEditing = !!existingCredentials;
  const maskedApiKey = existingCredentials?.api_key ?? "";

  const schema = Yup.object({
    apiKey: isEditing
      ? Yup.string().trim()
      : Yup.string().trim().required("API key is required"),
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
        if (await testAndSaveProviderCredentials({ provider, apiKey })) {
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
  const isEditing = !!existingCredentials;

  const schema = Yup.object({
    apiKey: isEditing
      ? Yup.string()
      : Yup.string()
          .required("Service account JSON is required")
          .test(
            "service-account-json",
            "Must be a valid Google service account JSON file",
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
}
function AzureProviderModal({
  provider,
  existingCredentials,
  onSubmit,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;
  const maskedApiKey = existingCredentials?.api_key ?? "";

  const schema = Yup.object({
    apiUrl: Yup.string()
      .trim()
      .required("Target URL is required")
      .url("Must be a valid URL"),
    apiKey: isEditing
      ? Yup.string().trim()
      : Yup.string().trim().required("API key is required"),
    apiVersion: Yup.string().trim().required("API version is required"),
    deploymentName: Yup.string().trim().required("Deployment name is required"),
  });

  const initialValues: AzureFormValues = {
    apiUrl: existingCredentials?.api_url ?? "",
    apiKey: maskedApiKey,
    apiVersion: existingCredentials?.api_version ?? "",
    deploymentName: existingCredentials?.deployment_name ?? "",
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
            apiUrl: values.apiUrl,
            apiVersion: values.apiVersion,
            deploymentName: values.deploymentName,
          })
        ) {
          onSubmit();
        }
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing}>
        <ApiUrlField
          title="Target URL"
          placeholder="https://your_resource_name.openai.azure.com/openai/v1/embeddings"
        />
        <ApiKeyField provider={provider} />
        <TextField
          name="apiVersion"
          title="API Version"
          placeholder="e.g., 2023-05-15"
          subDescription="The Azure OpenAI API version your deployment targets."
        />
        <TextField
          name="deploymentName"
          title="Deployment Name"
          placeholder="my-embedding-deployment"
          subDescription="The deployment name you configured for this embedding model in Azure."
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
  const isEditing = !!existingCredentials;
  const maskedApiKey = existingCredentials?.api_key ?? "";

  const schema = Yup.object({
    apiUrl: Yup.string()
      .trim()
      .required("API base URL is required")
      .url("Must be a valid URL"),
    apiKey: isEditing
      ? Yup.string().trim()
      : Yup.string().trim().required("API key is required"),
    ...modelSpecSchemaShape,
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
          title="API Base URL"
          placeholder="https://..."
          subDescription={`Paste your ${provider.displayName}-compatible endpoint URL.`}
        />

        <ApiKeyField provider={provider} />

        <ModelSpecFields
          modelNameSubDescription={`Onyx will connect to this model on your ${provider.displayName} proxy.`}
        />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// Custom Self-Hosted
// ---------------------------------------------------------------------------

const customSchema = Yup.object(modelSpecSchemaShape);
function CustomSelfHostedModal({
  provider,
  existingModel,
  onSubmit,
}: ProviderModalProps) {
  const isEditing = !!existingModel;

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
