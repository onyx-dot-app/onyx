"use client";

import { Formik, useFormikContext } from "formik";
import * as Yup from "yup";
import { Button } from "@opal/components";
import { SvgArrowExchange, SvgSimpleLoader } from "@opal/icons";
import { GlomiLogoMark } from "@/refresh-components/GlomiLogo";
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
          moreIcon2={GlomiLogoMark}
          title={
            isEditing
              ? `管理 ${provider.displayName}`
              : `设置 ${provider.displayName}`
          }
          description={
            isEditing
              ? `管理 ${provider.displayName} 服务商和模型详情。`
              : `连接 ${provider.displayName} 并设置 ${provider.displayName} 嵌入模型。`
          }
          onClose={onClose}
        />
        <Modal.Body twoTone>
          <GeneralLayouts.Section gap={1}>{children}</GeneralLayouts.Section>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            取消
          </Button>
          <Button
            disabled={!isValid || !dirty || isSubmitting}
            onClick={submitForm}
            icon={isSubmitting ? SvgSimpleLoader : undefined}
          >
            {isEditing ? "更新" : "连接"}
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
  modelName = "",
  apiVersion = null,
  deploymentName = null,
}: {
  provider: EmbeddingProvider;
  apiKey: string | null;
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
    toast.error(
      error instanceof Error ? error.message : "发生未知错误"
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
      : Yup.string().trim().required("请输入 API Key"),
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
          .required("请输入服务账号 JSON")
          .test(
            "service-account-json",
            "必须是有效的 Google 服务账号 JSON 文件",
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
  const isEditing = !!existingCredentials;
  const maskedApiKey = existingCredentials?.api_key ?? "";

  const schema = Yup.object({
    apiUrl: Yup.string()
      .trim()
      .required("请输入目标 URL")
      .url("必须是有效 URL"),
    apiKey: isEditing
      ? Yup.string().trim()
      : Yup.string().trim().required("请输入 API Key"),
    apiVersion: Yup.string().trim().required("请输入 API 版本"),
    deploymentName: Yup.string().trim().required("请输入部署名称"),
    ...modelSpecSchemaShape,
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
          title="目标 URL"
          placeholder="https://your_resource_name.openai.azure.com/openai/v1/embeddings"
        />
        <ApiKeyField provider={provider} />
        <TextField
          name="apiVersion"
          title="API 版本"
          placeholder="例如：2023-05-15"
          subDescription="此部署所使用的 Azure OpenAI API 版本。"
        />
        <TextField
          name="deploymentName"
          title="部署名称"
          placeholder="my-embedding-deployment"
          subDescription="你在 Azure 中为此嵌入模型配置的部署名称。"
        />

        <ModelSpecFields modelNameSubDescription="此模型在 Glomi AI 中的标签。Azure 会按部署名称路由请求，因此这里仅需填写唯一标识。" />
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
      .required("请输入 API Base URL")
      .url("必须是有效 URL"),
    apiKey: isEditing
      ? Yup.string().trim()
      : Yup.string().trim().required("请输入 API Key"),
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
            modelName: values.modelName.trim(),
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
          subDescription={`粘贴兼容 ${provider.displayName} 的端点 URL。`}
        />

        <ApiKeyField provider={provider} />

        <ModelSpecFields
          modelNameSubDescription={`Glomi AI 将连接到你 ${provider.displayName} 代理上的这个模型。`}
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
