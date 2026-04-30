"use client";

import { Formik, useFormikContext } from "formik";
import * as Yup from "yup";
import { Button, Divider } from "@opal/components";
import { SvgArrowExchange } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import * as GeneralLayouts from "@/layouts/general-layouts";
import Modal from "@/refresh-components/Modal";
import { toast } from "@/hooks/useToast";
import {
  EmbeddingProviderName,
  type ConfiguredEmbeddingProvider,
  type EmbeddingModel,
  type EmbeddingProvider,
} from "@/lib/indexing/interfaces";
import { connectEmbeddingProvider } from "@/lib/indexing/svc";
import {
  ApiKeyField,
  ApiUrlField,
  BoolField,
  GoogleCredentialsField,
  TextField,
} from "@/refresh-pages/admin/IndexSettingsPage/shared";

// ---------------------------------------------------------------------------
// Shared modal shell — reads `isValid`, `isSubmitting`, `submitForm` from the
// surrounding Formik context. Every modal in this file is wrapped in a
// `<Formik>` whose schema enforces field-level validation and whose
// `onSubmit` toasts backend errors instead of showing inline cards.
// ---------------------------------------------------------------------------

interface ModalShellProps {
  provider: EmbeddingProvider;
  isEditing: boolean;
  onCancel: () => void;
  children: React.ReactNode;
}

function ModalShell({
  provider,
  isEditing,
  onCancel,
  children,
}: ModalShellProps) {
  const { isValid, isSubmitting, submitForm } = useFormikContext();

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onCancel()}>
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
          onClose={onCancel}
        />
        <Modal.Body twoTone>
          <GeneralLayouts.Section gap={1}>{children}</GeneralLayouts.Section>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            disabled={!isValid || isSubmitting}
            onClick={() => void submitForm()}
          >
            {isSubmitting
              ? isEditing
                ? "Updating..."
                : "Connecting..."
              : isEditing
                ? "Update"
                : "Connect"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Shared connect helper — wraps `connectEmbeddingProvider` with the
// toast-on-failure convention. Returns `true` on success so callers can chain
// their own follow-up (e.g. staging a freshly-defined LiteLLM model).
//
// `apiUrl`, `apiVersion`, `deploymentName` default to "" / null so simple
// providers (OpenAI / Cohere / Voyage / Google) only have to pass `apiKey`.
// ---------------------------------------------------------------------------

async function submitProviderCredentials({
  provider,
  apiKey,
  apiUrl = "",
  apiVersion = null,
  deploymentName = null,
}: {
  provider: EmbeddingProvider;
  apiKey: string;
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
  onSubmit: (customModel?: EmbeddingModel) => void;
  onCancel: () => void;
}

// ---------------------------------------------------------------------------
// Standard provider modal (OpenAI, Cohere, Voyage)
// ---------------------------------------------------------------------------

interface StandardFormValues {
  apiKey: string;
}
const standardSchema: Yup.ObjectSchema<StandardFormValues> = Yup.object({
  apiKey: Yup.string().trim().required("API key is required"),
});
function StandardProviderModal({
  provider,
  existingCredentials,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;

  const initialValues: StandardFormValues = {
    apiKey: existingCredentials?.api_key ?? "",
  };

  return (
    <Formik<StandardFormValues>
      initialValues={initialValues}
      validationSchema={standardSchema}
      validateOnMount
      onSubmit={async (values) => {
        if (
          await submitProviderCredentials({ provider, apiKey: values.apiKey })
        ) {
          onSubmit();
        }
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing} onCancel={onCancel}>
        <ApiKeyField name="apiKey" provider={provider} />
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
const googleSchema: Yup.ObjectSchema<GoogleFormValues> = Yup.object({
  apiKey: Yup.string()
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
function GoogleProviderModal({
  provider,
  existingCredentials,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;

  const initialValues: GoogleFormValues = {
    apiKey: existingCredentials?.api_key ?? "",
  };

  return (
    <Formik<GoogleFormValues>
      initialValues={initialValues}
      validationSchema={googleSchema}
      validateOnMount
      onSubmit={async (values) => {
        if (
          await submitProviderCredentials({ provider, apiKey: values.apiKey })
        ) {
          onSubmit();
        }
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing} onCancel={onCancel}>
        <GoogleCredentialsField name="apiKey" />
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
const azureSchema: Yup.ObjectSchema<AzureFormValues> = Yup.object({
  apiUrl: Yup.string()
    .trim()
    .required("Target URL is required")
    .url("Must be a valid URL"),
  apiKey: Yup.string().trim().required("API key is required"),
  apiVersion: Yup.string().trim().required("API version is required"),
  deploymentName: Yup.string().trim().required("Deployment name is required"),
});
function AzureProviderModal({
  provider,
  existingCredentials,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;

  const initialValues: AzureFormValues = {
    apiUrl: existingCredentials?.api_url ?? "",
    apiKey: existingCredentials?.api_key ?? "",
    apiVersion: existingCredentials?.api_version ?? "",
    deploymentName: existingCredentials?.deployment_name ?? "",
  };

  return (
    <Formik<AzureFormValues>
      initialValues={initialValues}
      validationSchema={azureSchema}
      validateOnMount
      onSubmit={async (values) => {
        if (
          await submitProviderCredentials({
            provider,
            apiKey: values.apiKey,
            apiUrl: values.apiUrl,
            apiVersion: values.apiVersion,
            deploymentName: values.deploymentName,
          })
        ) {
          onSubmit();
        }
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing} onCancel={onCancel}>
        <ApiUrlField
          name="apiUrl"
          title="Target URL"
          placeholder="https://your_resource_name.openai.azure.com/openai/v1/embeddings"
        />
        <ApiKeyField name="apiKey" provider={provider} />
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
const litellmSchema: Yup.ObjectSchema<LiteLLMFormValues> = Yup.object({
  apiUrl: Yup.string()
    .trim()
    .required("API base URL is required")
    .url("Must be a valid URL"),
  apiKey: Yup.string().trim().required("API key is required"),
  modelName: Yup.string().trim().required("Model name is required"),
  modelDim: Yup.number()
    .required("Model dimension is required")
    .test("positive-int", "Must be a positive integer", (value) => {
      const parsed = Number(value);
      return Number.isInteger(parsed) && parsed > 0 && parsed <= 10000;
    }),
  queryPrefix: Yup.string().defined().default(""),
  passagePrefix: Yup.string().defined().default(""),
  normalize: Yup.boolean().defined().default(false),
});
function LiteLLMProviderModal({
  provider,
  existingCredentials,
  existingModel,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;

  const initialValues: LiteLLMFormValues = {
    apiUrl: existingCredentials?.api_url ?? "",
    apiKey: existingCredentials?.api_key ?? "",
    modelName: existingModel?.modelName ?? "",
    modelDim: existingModel?.modelDim ?? 0,
    queryPrefix: existingModel?.queryPrefix ?? "",
    passagePrefix: existingModel?.passagePrefix ?? "",
    normalize: existingModel?.normalize ?? false,
  };

  return (
    <Formik<LiteLLMFormValues>
      initialValues={initialValues}
      validationSchema={litellmSchema}
      validateOnMount
      onSubmit={async (values) => {
        if (
          await submitProviderCredentials({
            provider,
            apiKey: values.apiKey,
            apiUrl: values.apiUrl,
          })
        ) {
          onSubmit({
            modelName: values.modelName.trim(),
            modelDim: values.modelDim,
            normalize: values.normalize,
            queryPrefix: values.queryPrefix || null,
            passagePrefix: values.passagePrefix || null,
            description: "",
          });
        }
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing} onCancel={onCancel}>
        <ApiUrlField
          name="apiUrl"
          title="API Base URL"
          placeholder="https://..."
          subDescription={`Paste your ${provider.displayName}-compatible endpoint URL.`}
        />

        <ApiKeyField name="apiKey" provider={provider} />

        <TextField
          name="modelName"
          title="Model Name"
          placeholder="model-name"
          subDescription={`Onyx will connect to this model on your ${provider.displayName} proxy.`}
        />

        <Divider paddingParallel="fit" paddingPerpendicular="fit" />

        <TextField
          name="modelDim"
          title="Model Dimension"
          placeholder="e.g., 768"
          inputMode="numeric"
          subDescription="Number of dimensions in the embeddings generated by this model."
        />

        <TextField
          name="queryPrefix"
          title="Query Prefix"
          suffix="optional"
          placeholder="e.g., 'query: '"
          subDescription="This is prepended to search queries before passing to the model, if required by your embedding model. Incorrect or missing prefixes will degrade embedding quality."
        />

        <TextField
          name="passagePrefix"
          title="Passage Prefix"
          suffix="optional"
          placeholder="e.g., 'passage: '"
          subDescription="This is prepended to indexed document chunks before passing to the model, if required by your embedding model. Incorrect or missing prefixes will degrade embedding quality."
        />

        <BoolField
          name="normalize"
          title="Normalize Embeddings"
          description="Normalize the embeddings generated by the model. Recommended for most models unless your embedding model documentation specifies otherwise."
        />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// Custom Self-Hosted
// ---------------------------------------------------------------------------

interface CustomFormValues {
  modelName: string;
  modelDim: number;
  queryPrefix: string;
  passagePrefix: string;
  normalize: boolean;
}
const customSchema: Yup.ObjectSchema<CustomFormValues> = Yup.object({
  modelName: Yup.string().trim().required("Model name is required"),
  modelDim: Yup.number()
    .required("Model dimension is required")
    .test("positive-int", "Must be a positive integer", (value) => {
      const parsed = Number(value);
      return Number.isInteger(parsed) && parsed > 0 && parsed <= 10000;
    }),
  queryPrefix: Yup.string().defined().default(""),
  passagePrefix: Yup.string().defined().default(""),
  normalize: Yup.boolean().defined().default(false),
});
function CustomSelfHostedModal({
  provider,
  existingModel,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingModel;

  const initialValues: CustomFormValues = {
    modelName: existingModel?.modelName ?? "",
    modelDim: existingModel?.modelDim ?? 0,
    queryPrefix: existingModel?.queryPrefix ?? "",
    passagePrefix: existingModel?.passagePrefix ?? "",
    normalize: existingModel?.normalize ?? false,
  };

  return (
    <Formik<CustomFormValues>
      initialValues={initialValues}
      validationSchema={customSchema}
      validateOnMount
      onSubmit={(values) => {
        onSubmit({
          modelName: values.modelName.trim(),
          modelDim: values.modelDim,
          normalize: values.normalize,
          queryPrefix: values.queryPrefix || null,
          passagePrefix: values.passagePrefix || null,
          description: "",
        });
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing} onCancel={onCancel}>
        <TextField
          name="modelName"
          title="Model Name"
          placeholder="model-name"
          subDescription="Onyx will connect to this model on your self-hosted endpoint."
        />

        <Divider paddingParallel="fit" paddingPerpendicular="fit" />

        <TextField
          name="modelDim"
          title="Model Dimension"
          placeholder="e.g., 768"
          inputMode="numeric"
          subDescription="Number of dimensions in the embeddings generated by this model."
        />

        <TextField
          name="queryPrefix"
          title="Query Prefix"
          suffix="optional"
          placeholder="e.g., 'query: '"
          subDescription="This is prepended to search queries before passing to the model, if required by your embedding model. Incorrect or missing prefixes will degrade embedding quality."
        />

        <TextField
          name="passagePrefix"
          title="Passage Prefix"
          suffix="optional"
          placeholder="e.g., 'passage: '"
          subDescription="This is prepended to indexed document chunks before passing to the model, if required by your embedding model. Incorrect or missing prefixes will degrade embedding quality."
        />

        <BoolField
          name="normalize"
          title="Normalize Embeddings"
          description="Normalize the embeddings generated by the model. Recommended for most models unless your embedding model documentation specifies otherwise."
        />
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
