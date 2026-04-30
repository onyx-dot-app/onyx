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
} from "./shared";

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
// Shared submit helper — wraps `connectEmbeddingProvider` with the toast-on-
// failure convention so each modal's `onSubmit` stays a one-liner.
// ---------------------------------------------------------------------------

async function submitProviderCredentials(
  provider: EmbeddingProvider,
  apiKey: string,
  apiUrl: string,
  onSuccess: () => void
): Promise<void> {
  try {
    await connectEmbeddingProvider({
      providerType: provider.providerName,
      apiKey,
      apiUrl,
    });
    onSuccess();
  } catch (error: unknown) {
    toast.error(
      error instanceof Error ? error.message : "An unknown error occurred"
    );
  }
}

// ---------------------------------------------------------------------------
// Shared props
// ---------------------------------------------------------------------------

export interface ProviderModalProps {
  provider: EmbeddingProvider;
  existingCredentials?: ConfiguredEmbeddingProvider;
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

export function StandardProviderModal({
  provider,
  existingCredentials,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;

  return (
    <Formik<StandardFormValues>
      initialValues={{ apiKey: existingCredentials?.api_key ?? "" }}
      validationSchema={standardSchema}
      validateOnMount
      onSubmit={async (values) => {
        await submitProviderCredentials(provider, values.apiKey, "", onSubmit);
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing} onCancel={onCancel}>
        <ApiKeyField
          name="apiKey"
          apiLink={provider.apiLink ?? ""}
          providerName={provider.displayName}
        />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// Google provider modal (JSON file upload)
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

export function GoogleProviderModal({
  provider,
  existingCredentials,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;

  return (
    <Formik<GoogleFormValues>
      initialValues={{ apiKey: existingCredentials?.api_key ?? "" }}
      validationSchema={googleSchema}
      validateOnMount
      onSubmit={async (values) => {
        await submitProviderCredentials(provider, values.apiKey, "", onSubmit);
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing} onCancel={onCancel}>
        <GoogleCredentialsField name="apiKey" />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// Azure provider modal (Target URL + API Key)
// ---------------------------------------------------------------------------

interface AzureFormValues {
  apiUrl: string;
  apiKey: string;
}

const azureSchema: Yup.ObjectSchema<AzureFormValues> = Yup.object({
  apiUrl: Yup.string()
    .trim()
    .required("Target URL is required")
    .url("Must be a valid URL"),
  apiKey: Yup.string().trim().required("API key is required"),
});

export function AzureProviderModal({
  provider,
  existingCredentials,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;

  return (
    <Formik<AzureFormValues>
      initialValues={{
        apiUrl: existingCredentials?.api_url ?? "",
        apiKey: existingCredentials?.api_key ?? "",
      }}
      validationSchema={azureSchema}
      validateOnMount
      onSubmit={async (values) => {
        await submitProviderCredentials(
          provider,
          values.apiKey,
          values.apiUrl,
          onSubmit
        );
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing} onCancel={onCancel}>
        <ApiUrlField
          name="apiUrl"
          title="Target URL"
          placeholder="https://your_resource_name.openai.azure.com/openai/v1/embeddings"
        />
        <ApiKeyField
          name="apiKey"
          apiLink={provider.apiLink ?? ""}
          providerName={provider.displayName}
        />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// LiteLLM provider modal (full config)
// ---------------------------------------------------------------------------

interface LiteLLMFormValues {
  apiUrl: string;
  apiKey: string;
  modelName: string;
  modelDim: string;
  queryPrefix: string;
  passagePrefix: string;
  normalize: boolean;
}

const litellmSchema: Yup.ObjectSchema<LiteLLMFormValues> = Yup.object({
  apiUrl: Yup.string()
    .trim()
    .required("API base URL is required")
    .url("Must be a valid URL"),
  apiKey: Yup.string().defined().default(""),
  modelName: Yup.string().trim().required("Model name is required"),
  modelDim: Yup.string()
    .required("Model dimension is required")
    .test("positive-int", "Must be a positive integer", (value) => {
      const parsed = Number(value);
      return Number.isInteger(parsed) && parsed > 0 && parsed <= 10000;
    }),
  queryPrefix: Yup.string().defined().default(""),
  passagePrefix: Yup.string().defined().default(""),
  normalize: Yup.boolean().defined().default(false),
});

export function LiteLLMProviderModal({
  provider,
  existingCredentials,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;

  return (
    <Formik<LiteLLMFormValues>
      initialValues={{
        apiUrl: existingCredentials?.api_url ?? "",
        apiKey: existingCredentials?.api_key ?? "",
        modelName: "",
        modelDim: "",
        queryPrefix: "",
        passagePrefix: "",
        normalize: false,
      }}
      validationSchema={litellmSchema}
      validateOnMount
      onSubmit={async (values) => {
        await submitProviderCredentials(
          provider,
          values.apiKey,
          values.apiUrl,
          onSubmit
        );
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing} onCancel={onCancel}>
        <ApiUrlField
          name="apiUrl"
          title="API Base URL"
          placeholder="https://..."
          subDescription={`Paste your ${provider.displayName}-compatible endpoint URL.`}
        />

        <ApiKeyField
          name="apiKey"
          apiLink={provider.apiLink ?? ""}
          providerName={provider.displayName}
        />

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
// Custom self-hosted model modal
// ---------------------------------------------------------------------------

interface CustomFormValues {
  modelName: string;
  modelDim: string;
  queryPrefix: string;
  passagePrefix: string;
  normalize: boolean;
}

const customSchema: Yup.ObjectSchema<CustomFormValues> = Yup.object({
  modelName: Yup.string().trim().required("Model name is required"),
  modelDim: Yup.string()
    .required("Model dimension is required")
    .test("positive-int", "Must be a positive integer", (value) => {
      const parsed = Number(value);
      return Number.isInteger(parsed) && parsed > 0 && parsed <= 10000;
    }),
  queryPrefix: Yup.string().defined().default(""),
  passagePrefix: Yup.string().defined().default(""),
  normalize: Yup.boolean().defined().default(false),
});

export function CustomSelfHostedModal({
  provider,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  return (
    <Formik<CustomFormValues>
      initialValues={{
        modelName: "",
        modelDim: "",
        queryPrefix: "",
        passagePrefix: "",
        normalize: false,
      }}
      validationSchema={customSchema}
      validateOnMount
      onSubmit={(values) => {
        onSubmit({
          modelName: values.modelName.trim(),
          modelDim: parseInt(values.modelDim, 10),
          normalize: values.normalize,
          queryPrefix: values.queryPrefix || null,
          passagePrefix: values.passagePrefix || null,
          description: "",
        });
      }}
    >
      <Modal open onOpenChange={(isOpen) => !isOpen && onCancel()}>
        <Modal.Content width="md">
          <Modal.Header
            icon={provider.icon}
            moreIcon1={SvgArrowExchange}
            moreIcon2={SvgOnyxLogo}
            title={`Add ${provider.displayName}`}
            description="Register a custom self-hosted embedding model."
            onClose={onCancel}
          />
          <Modal.Body twoTone>
            <GeneralLayouts.Section gap={1}>
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
            </GeneralLayouts.Section>
          </Modal.Body>
          <Modal.Footer>
            <Button prominence="secondary" onClick={onCancel}>
              Cancel
            </Button>
            <CustomSelfHostedSubmitButton />
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </Formik>
  );
}

function CustomSelfHostedSubmitButton() {
  const { isValid, submitForm } = useFormikContext();
  return (
    <Button disabled={!isValid} onClick={() => void submitForm()}>
      Connect
    </Button>
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
