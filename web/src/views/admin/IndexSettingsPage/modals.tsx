"use client";

import { IconLoader } from "@opal/loaders";
import { Formik, useFormikContext } from "formik";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import * as Yup from "yup";
import { Button } from "@opal/components";
import { SvgArrowExchange } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { Modal } from "@opal/components";
import { InputVertical, toast } from "@opal/layouts";
import { InputSingleSelectField } from "@opal/form";
import {
  EmbeddingModelRequest,
  EmbeddingProviderName,
  type ConfiguredEmbeddingProvider,
  type EmbeddingModel,
  type EmbeddingProvider,
  type VertexEmbeddingConfig,
} from "@/lib/searchSettings/types";
import {
  connectEmbeddingProvider,
  testEmbedding,
} from "@/lib/searchSettings/svc";
import { ApiTokenField } from "@/lib/api-tokens/components";
import type { ApiTokenValue } from "@/lib/api-tokens/types";
import {
  initialApiTokenValue,
  toApiTokenPayload,
} from "@/lib/api-tokens/utils";
import { apiTokenSchema } from "@/lib/api-tokens/validation";
import {
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
            icon={isSubmitting ? IconLoader : undefined}
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
// Returns the test result on success so callers can chain their own follow-up
// (e.g. staging a freshly-defined LiteLLM model). `dimension` is the test
// vector length, or null when no test ran. On failure, toasts the error and
// returns `null`.
//
// `apiUrl`, `apiVersion`, `deploymentName` default to "" / null so simple
// providers (OpenAI / Cohere / Voyage / Google) only have to pass `apiKey`.
// ---------------------------------------------------------------------------

interface ProviderTestResult {
  dimension: number | null;
}

async function testAndSaveProviderCredentials({
  provider,
  apiKey,
  savedTokenId = null,
  unknownErrorMessage,
  apiUrl = "",
  modelName = "",
  apiVersion = null,
  deploymentName = null,
  vertexConfig,
  alwaysTest = false,
}: {
  provider: EmbeddingProvider;
  apiKey: ApiTokenValue | null;
  /** The token the saved provider already uses, if any. */
  savedTokenId?: number | null;
  /** Fallback toast copy when the backend error carries no message. */
  unknownErrorMessage: string;
  apiUrl?: string;
  modelName?: string;
  apiVersion?: string | null;
  deploymentName?: string | null;
  vertexConfig?: VertexEmbeddingConfig | null;
  alwaysTest?: boolean;
}): Promise<ProviderTestResult | null> {
  try {
    const dimension = await connectEmbeddingProvider({
      providerType: provider.providerName,
      apiKey,
      savedTokenId,
      apiUrl,
      modelName,
      apiVersion,
      deploymentName,
      vertexConfig,
      alwaysTest,
    });
    return { dimension };
  } catch (error: unknown) {
    toast.error(error instanceof Error ? error.message : unknownErrorMessage);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Shared props
// ---------------------------------------------------------------------------

interface ProviderModalProps {
  provider: EmbeddingProvider;
  existingCredentials?: ConfiguredEmbeddingProvider;
  /**
   * Model being connected, selected, or edited for this provider. Google
   * tests this model. Custom providers also use it to preload model fields.
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
// API key field, bound to the `apiKey` form value
// ---------------------------------------------------------------------------

interface EmbeddingApiTokenFieldProps {
  provider: EmbeddingProvider;
  existingCredentials?: ConfiguredEmbeddingProvider;
  optional?: boolean;
}

function EmbeddingApiTokenField({
  provider,
  existingCredentials,
  optional = false,
}: EmbeddingApiTokenFieldProps) {
  return (
    <ApiTokenField
      name="apiKey"
      platform={provider.providerName}
      optional={optional}
      savedMaskedValue={existingCredentials?.api_key ?? undefined}
    />
  );
}

// ---------------------------------------------------------------------------
// Standard provider modal (OpenAI, Cohere, Voyage)
// ---------------------------------------------------------------------------

interface StandardFormValues {
  apiKey: ApiTokenValue;
}
function StandardProviderModal({
  provider,
  existingCredentials,
  onSubmit,
}: ProviderModalProps) {
  const t = useTranslations("admin.indexSettings");
  const isEditing = !!existingCredentials;
  const savedTokenId = existingCredentials?.api_token_id ?? null;

  const schema = Yup.object({
    apiKey: apiTokenSchema(t("validation.apiKeyRequired")),
  });

  const initialValues: StandardFormValues = {
    apiKey: initialApiTokenValue(savedTokenId),
  };

  return (
    <Formik<StandardFormValues>
      initialValues={initialValues}
      validationSchema={schema}
      validateOnMount
      onSubmit={async (values) => {
        if (
          await testAndSaveProviderCredentials({
            provider,
            apiKey: toApiTokenPayload(values.apiKey),
            savedTokenId,
            unknownErrorMessage: t("toasts.unknownError"),
          })
        ) {
          onSubmit();
        }
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing}>
        <EmbeddingApiTokenField
          provider={provider}
          existingCredentials={existingCredentials}
        />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// Google
// ---------------------------------------------------------------------------

interface GoogleFormValues {
  apiKey: string;
  authMethod: VertexEmbeddingConfig["auth_method"];
  projectId: string;
  location: string;
}

function GoogleAuthenticationFields() {
  const t = useTranslations("admin.indexSettings");
  const tVertex = useTranslations("admin.languageModels.modals.vertexAi");
  const tSelect = useTranslations("common.inputSelect");
  const { values, setFieldValue } = useFormikContext<GoogleFormValues>();
  const settings = useSettings();
  return (
    <>
      {settings.hooks_enabled && (
        <InputVertical
          withLabel="authMethod"
          title={tVertex("authMethodField.title")}
        >
          <InputSingleSelectField
            name="authMethod"
            defaultOption="service_account_json"
            placeholder={tSelect("placeholder.fallback")}
            options={[
              {
                value: "service_account_json",
                title: tVertex("authMethodField.serviceAccount.label"),
              },
              {
                value: "workload_identity",
                title: tVertex("authMethodField.workloadIdentity.label"),
              },
            ]}
            onValueChange={() => {
              void setFieldValue("apiKey", "");
            }}
          />
        </InputVertical>
      )}
      {values.authMethod === "workload_identity" ? (
        <TextField
          name="projectId"
          title={tVertex("projectField.title")}
          subDescription={t("fields.googleWorkloadIdentity.description")}
          placeholder={tVertex("projectField.placeholder")}
        />
      ) : (
        <GoogleCredentialsField />
      )}
      <TextField
        name="location"
        title={tVertex("locationField.title")}
        subDescription={tVertex("locationField.description")}
        placeholder={tVertex("locationField.placeholder")}
      />
    </>
  );
}

function GoogleProviderModal({
  provider,
  existingCredentials,
  existingModel,
  onSubmit,
}: ProviderModalProps) {
  const t = useTranslations("admin.indexSettings");
  const isEditing = !!existingCredentials;
  const existingConfig = existingCredentials?.vertex_config;
  const savedTokenId = existingCredentials?.api_token_id ?? null;

  const schema = Yup.object({
    authMethod: Yup.string()
      .oneOf(["service_account_json", "workload_identity"])
      .required(),
    projectId: Yup.string()
      .trim()
      .when("authMethod", {
        is: "workload_identity",
        then: (schema) =>
          schema.required(t("validation.googleProjectRequired")),
      }),
    location: Yup.string().trim(),
    apiKey: Yup.string().when("authMethod", {
      is: "service_account_json",
      then: (schema) =>
        schema.test(
          "service-account-json",
          t("validation.serviceAccountJsonInvalid"),
          (value) => {
            if (!value)
              return (
                isEditing && existingConfig?.auth_method !== "workload_identity"
              );
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
    }),
  });

  const initialValues: GoogleFormValues = {
    apiKey: "",
    authMethod: existingConfig?.auth_method ?? "service_account_json",
    projectId: existingConfig?.project_id ?? "",
    location: existingConfig?.location ?? "",
  };

  return (
    <Formik<GoogleFormValues>
      initialValues={initialValues}
      validationSchema={schema}
      validateOnMount
      onSubmit={async (values) => {
        // An empty upload keeps the saved service account JSON.
        const apiKey: ApiTokenValue | null = values.apiKey
          ? { type: "new", value: values.apiKey }
          : savedTokenId !== null
            ? { type: "existing", id: savedTokenId }
            : null;
        if (
          await testAndSaveProviderCredentials({
            provider,
            apiKey,
            savedTokenId,
            vertexConfig: {
              auth_method: values.authMethod,
              project_id:
                values.authMethod === "workload_identity"
                  ? values.projectId.trim()
                  : null,
              location: values.location.trim() || null,
            },
            modelName:
              existingModel?.modelName ??
              provider.embeddingModels[0]?.modelName ??
              "",
            unknownErrorMessage: t("toasts.unknownError"),
          })
        ) {
          onSubmit();
        }
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing}>
        <GoogleAuthenticationFields />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// Azure
// ---------------------------------------------------------------------------

interface AzureFormValues {
  apiUrl: string;
  apiKey: ApiTokenValue;
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
  const tPlaceholders = useTranslations("common.placeholders");
  const { appName } = useSettings();
  const isEditing = !!existingCredentials;
  const savedTokenId = existingCredentials?.api_token_id ?? null;

  const schema = Yup.object({
    apiUrl: Yup.string()
      .trim()
      .required(t("validation.targetUrlRequired"))
      .url(t("validation.urlInvalid")),
    apiKey: apiTokenSchema(t("validation.apiKeyRequired")),
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
    apiKey: initialApiTokenValue(savedTokenId),
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
        if (
          await testAndSaveProviderCredentials({
            provider,
            apiKey: toApiTokenPayload(values.apiKey),
            savedTokenId,
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
          placeholder={tPlaceholders("azure.embeddingsUrl")}
        />
        <EmbeddingApiTokenField
          provider={provider}
          existingCredentials={existingCredentials}
        />
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
          modelNameSubDescription={t("azure.modelName.description", {
            appName,
          })}
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
  apiKey: ApiTokenValue;
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
  const { appName } = useSettings();
  const isEditing = !!existingCredentials;
  const savedTokenId = existingCredentials?.api_token_id ?? null;

  const schema = Yup.object({
    apiUrl: Yup.string()
      .trim()
      .required(t("validation.apiBaseUrlRequired"))
      .url(t("validation.urlInvalid")),
    // LiteLLM works without a key, so an edit may clear it.
    apiKey: isEditing
      ? apiTokenSchema()
      : apiTokenSchema(t("validation.apiKeyRequired")),
    ...modelSpecSchemaShape(t),
  });

  const initialValues: LiteLLMFormValues = {
    apiUrl: existingCredentials?.api_url ?? "",
    apiKey: initialApiTokenValue(savedTokenId),
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
        if (
          await testAndSaveProviderCredentials({
            provider,
            apiKey: toApiTokenPayload(values.apiKey),
            savedTokenId,
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
          placeholder={t("placeholders.apiUrl")}
          subDescription={t("litellm.apiUrl.description", {
            provider: provider.displayName,
          })}
        />

        <EmbeddingApiTokenField
          provider={provider}
          existingCredentials={existingCredentials}
        />

        <ModelSpecFields
          modelNameSubDescription={t("litellm.modelName.description", {
            provider: provider.displayName,
            appName,
          })}
        />
      </ModalShell>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// Bifrost — the model is free text. Every save embeds a test string, which
// rejects non-embedding models and gives the dimension.
// ---------------------------------------------------------------------------

function isHttpUrl(value: string | undefined): boolean {
  if (!value) return false;
  try {
    const { protocol, hostname } = new URL(value.trim());
    return (protocol === "http:" || protocol === "https:") && hostname !== "";
  } catch {
    return false;
  }
}

interface BifrostFormValues {
  apiUrl: string;
  apiKey: ApiTokenValue;
  modelName: string;
}
function BifrostProviderModal({
  provider,
  existingCredentials,
  existingModel,
  onSubmit,
}: ProviderModalProps) {
  const t = useTranslations("admin.indexSettings");
  const tPlaceholders = useTranslations("common.placeholders");
  const { appName } = useSettings();
  const isEditing = !!existingCredentials;
  const savedTokenId = existingCredentials?.api_token_id ?? null;
  // Editing manages the connection only; another model is picked from the
  // model list. The kept model is tested against the new URL and key.
  const isModelLocked = isEditing && !!existingModel;

  const schema = Yup.object({
    apiUrl: Yup.string()
      .trim()
      .required(t("validation.apiBaseUrlRequired"))
      // Yup's .url() rejects in-cluster hosts such as http://bifrost:8080.
      .test("http-url", t("validation.urlInvalid"), isHttpUrl),
    apiKey: apiTokenSchema(),
    modelName: Yup.string().trim().required(t("validation.modelNameRequired")),
  });

  const initialValues: BifrostFormValues = {
    apiUrl: existingCredentials?.api_url ?? "",
    apiKey: initialApiTokenValue(savedTokenId),
    modelName: existingModel?.modelName ?? "",
  };

  return (
    <Formik<BifrostFormValues>
      initialValues={initialValues}
      validationSchema={schema}
      validateOnMount
      onSubmit={async (values) => {
        const modelName = values.modelName.trim();
        const result = await testAndSaveProviderCredentials({
          provider,
          apiKey: toApiTokenPayload(values.apiKey),
          savedTokenId,
          apiUrl: values.apiUrl.trim(),
          modelName,
          alwaysTest: true,
          unknownErrorMessage: t("toasts.unknownError"),
        });
        if (result?.dimension) {
          onSubmit({
            modelName,
            modelDim: result.dimension,
            normalize: false,
            queryPrefix: null,
            passagePrefix: null,
          });
        }
      }}
    >
      <ModalShell provider={provider} isEditing={isEditing}>
        <ApiUrlField
          title={t("bifrost.apiUrl.title")}
          placeholder={tPlaceholders("bifrost.embeddingsApiBase")}
          subDescription={t("bifrost.apiUrl.description", { appName })}
        />

        <EmbeddingApiTokenField
          provider={provider}
          existingCredentials={existingCredentials}
          optional
        />

        <TextField
          name="modelName"
          title={t("fields.modelName.title")}
          placeholder={tPlaceholders("bifrost.embeddingModel")}
          subDescription={
            isModelLocked
              ? t("bifrost.modelName.editDescription", { appName })
              : t("bifrost.modelName.description", { appName })
          }
          readOnly={isModelLocked}
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
    case EmbeddingProviderName.BIFROST:
      return <BifrostProviderModal {...props} />;
    case EmbeddingProviderName.CUSTOM:
      return <CustomSelfHostedModal {...props} />;
    default:
      return <StandardProviderModal {...props} />;
  }
}
