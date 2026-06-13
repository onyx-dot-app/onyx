"use client";

import { useEffect } from "react";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { FileUploadFormField } from "@/components/Field";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Card, MessageCard } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { InputDivider, InputPadder, InputVertical } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/lib/languageModels/types";
import * as Yup from "yup";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics";
import {
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import { toast } from "@/hooks/useToast";
import { useSettingsContext } from "@/providers/SettingsProvider";

const VERTEXAI_DEFAULT_LOCATION = "global";

const AUTH_METHOD_SERVICE_ACCOUNT = "service_account_json";
const AUTH_METHOD_WORKLOAD_IDENTITY = "workload_identity";

const FIELD_VERTEX_AUTH_METHOD = "custom_config.vertex_auth_method";
const FIELD_VERTEX_CREDENTIALS = "custom_config.vertex_credentials";
const FIELD_VERTEX_LOCATION = "custom_config.vertex_location";
const FIELD_VERTEX_PROJECT = "custom_config.vertex_project";

interface VertexAIModalValues extends BaseLLMFormValues {
  custom_config: {
    vertex_auth_method: string;
    vertex_credentials: string;
    vertex_location: string;
    vertex_project: string;
  };
}

interface VertexAIModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function VertexAIModalInternals({
  existingLlmProvider,
  isOnboarding,
}: VertexAIModalInternalsProps) {
  const formikProps = useFormikContext<VertexAIModalValues>();
  const authMethod = formikProps.values.custom_config?.vertex_auth_method;
  const settingsContext = useSettingsContext();
  const isMultiTenant = !settingsContext.settings.hooks_enabled;

  useEffect(() => {
    if (authMethod === AUTH_METHOD_WORKLOAD_IDENTITY) {
      formikProps.setFieldValue(FIELD_VERTEX_CREDENTIALS, "");
    } else if (authMethod === AUTH_METHOD_SERVICE_ACCOUNT) {
      formikProps.setFieldValue(FIELD_VERTEX_PROJECT, "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authMethod]);

  const showAuthMethodSelector = !isMultiTenant;

  return (
    <>
      <InputPadder>
        <Section gap={1}>
          {showAuthMethodSelector && (
            <InputVertical
              withLabel={FIELD_VERTEX_AUTH_METHOD}
              title="认证方式"
              subDescription="选择 Glomi AI 如何与 Google Vertex AI 进行认证。"
            >
              <InputSelectField name={FIELD_VERTEX_AUTH_METHOD}>
                <InputSelect.Trigger />
                <InputSelect.Content>
                  <InputSelect.Item
                    value={AUTH_METHOD_SERVICE_ACCOUNT}
                    description="上传 GCP 服务账号 Key JSON 文件"
                  >
                    服务账号 JSON
                  </InputSelect.Item>
                  <InputSelect.Item
                    value={AUTH_METHOD_WORKLOAD_IDENTITY}
                    description="使用 Pod 环境中的 GCP 凭据（GKE Workload Identity）"
                  >
                    Workload Identity (GKE)
                  </InputSelect.Item>
                </InputSelect.Content>
              </InputSelectField>
            </InputVertical>
          )}

          <InputVertical
            withLabel={FIELD_VERTEX_LOCATION}
            title="Google Cloud 区域名称"
            subDescription="托管 Google Vertex AI 模型的区域。支持区域完整列表请查看 Google Cloud。"
          >
            <InputTypeInField
              name={FIELD_VERTEX_LOCATION}
              placeholder={VERTEXAI_DEFAULT_LOCATION}
            />
          </InputVertical>
        </Section>
      </InputPadder>

      {authMethod === AUTH_METHOD_SERVICE_ACCOUNT && (
        <InputPadder>
          <InputVertical
            withLabel={FIELD_VERTEX_CREDENTIALS}
            title="API Key"
            subDescription="上传来自 Google Cloud 的 API Key JSON 以访问你的模型。"
          >
            <FileUploadFormField name={FIELD_VERTEX_CREDENTIALS} label="" />
          </InputVertical>
        </InputPadder>
      )}

      {authMethod === AUTH_METHOD_WORKLOAD_IDENTITY && (
        <>
          <InputPadder>
            <MessageCard
              variant="info"
              title="Glomi AI 将使用 Pod 环境中的 Google Cloud 凭据（通过 google.auth.default）。请确保 Kubernetes ServiceAccount 已绑定到有权访问 Vertex AI 的 GCP Service Account。"
            />
          </InputPadder>
          <Card background="light" border="none" padding="sm">
            <InputVertical
              withLabel={FIELD_VERTEX_PROJECT}
              title="GCP Project ID"
              subDescription="已启用 Vertex AI 的 GCP 项目。由于使用服务账号模拟时 ADC 无法可靠推断目标项目，因此此项必填。"
            >
              <InputTypeInField
                name={FIELD_VERTEX_PROJECT}
                placeholder="my-vertex-project"
              />
            </InputVertical>
          </Card>
        </>
      )}

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputDivider />
      <ModelSelectionField shouldShowAutoUpdateToggle={true} />

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </>
  );
}

export default function VertexAIModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues: VertexAIModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.VERTEX_AI,
      existingLlmProvider
    ),
    custom_config: {
      vertex_auth_method:
        (existingLlmProvider?.custom_config?.vertex_auth_method as string) ??
        AUTH_METHOD_SERVICE_ACCOUNT,
      vertex_credentials:
        (existingLlmProvider?.custom_config?.vertex_credentials as string) ??
        "",
      vertex_location:
        (existingLlmProvider?.custom_config?.vertex_location as string) ??
        VERTEXAI_DEFAULT_LOCATION,
      vertex_project:
        (existingLlmProvider?.custom_config?.vertex_project as string) ?? "",
    },
  } as VertexAIModalValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
    extra: {
      custom_config: Yup.object({
        vertex_auth_method: Yup.string().required(
          "请选择认证方式"
        ),
        vertex_location: Yup.string(),
        vertex_credentials: Yup.string().when("vertex_auth_method", {
          is: AUTH_METHOD_SERVICE_ACCOUNT,
          then: (schema) => schema.required("请上传凭据文件"),
          otherwise: (schema) => schema.notRequired(),
        }),
        vertex_project: Yup.string().when("vertex_auth_method", {
          is: AUTH_METHOD_WORKLOAD_IDENTITY,
          then: (schema) => schema.required("请输入 GCP Project ID"),
          otherwise: (schema) => schema.notRequired(),
        }),
      }),
    },
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.VERTEX_AI}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        const filteredCustomConfig = Object.fromEntries(
          Object.entries(values.custom_config || {}).filter(
            ([key, v]) => key === "vertex_auth_method" || v !== ""
          )
        );

        const submitValues = {
          ...values,
          custom_config:
            Object.keys(filteredCustomConfig).length > 0
              ? filteredCustomConfig
              : undefined,
        };

        await submitProvider({
          analyticsSource: isOnboarding
            ? LLMProviderConfiguredSource.CHAT_ONBOARDING
            : LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: LLMProviderName.VERTEX_AI,
          values: submitValues,
          initialValues,
          existingLlmProvider,
          shouldMarkAsDefault,
          setStatus,
          setSubmitting,
          onClose,
          onSuccess: async () => {
            if (onSuccess) {
              await onSuccess();
            } else {
              await refreshLlmProviderCaches(mutate);
              toast.success(
                existingLlmProvider
                  ? "服务商已更新！"
                  : "服务商已启用！"
              );
            }
          },
        });
      }}
    >
      <VertexAIModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
