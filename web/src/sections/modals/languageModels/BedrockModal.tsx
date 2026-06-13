"use client";

import { useEffect } from "react";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
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
  mergeFetchedModelConfigurations,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics";
import {
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";
import { fetchBedrockModels } from "@/lib/languageModels/svc";
import { Card, MessageCard } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { InputDivider, InputPadder, InputVertical } from "@opal/layouts";
import { toast } from "@/hooks/useToast";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";

const AWS_REGION_OPTIONS = [
  { name: "us-east-1", value: "us-east-1" },
  { name: "us-east-2", value: "us-east-2" },
  { name: "us-west-2", value: "us-west-2" },
  { name: "us-gov-east-1", value: "us-gov-east-1" },
  { name: "us-gov-west-1", value: "us-gov-west-1" },
  { name: "ap-northeast-1", value: "ap-northeast-1" },
  { name: "ap-south-1", value: "ap-south-1" },
  { name: "ap-southeast-1", value: "ap-southeast-1" },
  { name: "ap-southeast-2", value: "ap-southeast-2" },
  { name: "ap-east-1", value: "ap-east-1" },
  { name: "ca-central-1", value: "ca-central-1" },
  { name: "eu-central-1", value: "eu-central-1" },
  { name: "eu-west-2", value: "eu-west-2" },
];
const AUTH_METHOD_IAM = "iam";
const AUTH_METHOD_ACCESS_KEY = "access_key";
const AUTH_METHOD_LONG_TERM_API_KEY = "long_term_api_key";
const FIELD_AWS_REGION_NAME = "custom_config.AWS_REGION_NAME";
const FIELD_BEDROCK_AUTH_METHOD = "custom_config.BEDROCK_AUTH_METHOD";
const FIELD_AWS_ACCESS_KEY_ID = "custom_config.AWS_ACCESS_KEY_ID";
const FIELD_AWS_SECRET_ACCESS_KEY = "custom_config.AWS_SECRET_ACCESS_KEY";
const FIELD_AWS_BEARER_TOKEN_BEDROCK = "custom_config.AWS_BEARER_TOKEN_BEDROCK";

interface BedrockModalValues extends BaseLLMFormValues {
  custom_config: {
    AWS_REGION_NAME: string;
    BEDROCK_AUTH_METHOD?: string;
    AWS_ACCESS_KEY_ID?: string;
    AWS_SECRET_ACCESS_KEY?: string;
    AWS_BEARER_TOKEN_BEDROCK?: string;
  };
}

interface BedrockModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function BedrockModalInternals({
  existingLlmProvider,
  isOnboarding,
}: BedrockModalInternalsProps) {
  const formikProps = useFormikContext<BedrockModalValues>();
  const authMethod = formikProps.values.custom_config?.BEDROCK_AUTH_METHOD;

  useEffect(() => {
    if (authMethod === AUTH_METHOD_IAM) {
      formikProps.setFieldValue(FIELD_AWS_ACCESS_KEY_ID, "");
      formikProps.setFieldValue(FIELD_AWS_SECRET_ACCESS_KEY, "");
      formikProps.setFieldValue(FIELD_AWS_BEARER_TOKEN_BEDROCK, "");
    } else if (authMethod === AUTH_METHOD_ACCESS_KEY) {
      formikProps.setFieldValue(FIELD_AWS_BEARER_TOKEN_BEDROCK, "");
    } else if (authMethod === AUTH_METHOD_LONG_TERM_API_KEY) {
      formikProps.setFieldValue(FIELD_AWS_ACCESS_KEY_ID, "");
      formikProps.setFieldValue(FIELD_AWS_SECRET_ACCESS_KEY, "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authMethod]);

  const isAuthComplete =
    authMethod === AUTH_METHOD_IAM ||
    (authMethod === AUTH_METHOD_ACCESS_KEY &&
      formikProps.values.custom_config?.AWS_ACCESS_KEY_ID &&
      formikProps.values.custom_config?.AWS_SECRET_ACCESS_KEY) ||
    (authMethod === AUTH_METHOD_LONG_TERM_API_KEY &&
      formikProps.values.custom_config?.AWS_BEARER_TOKEN_BEDROCK);

  const isFetchDisabled =
    !formikProps.values.custom_config?.AWS_REGION_NAME || !isAuthComplete;

  const handleFetchModels = async () => {
    const { models, error } = await fetchBedrockModels({
      aws_region_name: formikProps.values.custom_config?.AWS_REGION_NAME ?? "",
      aws_access_key_id: formikProps.values.custom_config?.AWS_ACCESS_KEY_ID,
      aws_secret_access_key:
        formikProps.values.custom_config?.AWS_SECRET_ACCESS_KEY,
      aws_bearer_token_bedrock:
        formikProps.values.custom_config?.AWS_BEARER_TOKEN_BEDROCK,
      provider_name: LLMProviderName.BEDROCK,
    });
    if (error) {
      throw new Error(error);
    }
    formikProps.setFieldValue(
      "model_configurations",
      mergeFetchedModelConfigurations(
        models,
        formikProps.values.model_configurations
      )
    );
  };

  return (
    <>
      <InputPadder>
        <Section gap={1}>
          <InputVertical
            withLabel={FIELD_AWS_REGION_NAME}
            title="AWS 区域"
            subDescription="托管 Amazon Bedrock 模型的区域。"
          >
            <InputSelectField name={FIELD_AWS_REGION_NAME}>
              <InputSelect.Trigger placeholder="选择区域" />
              <InputSelect.Content>
                {AWS_REGION_OPTIONS.map((option) => (
                  <InputSelect.Item key={option.value} value={option.value}>
                    {option.name}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelectField>
          </InputVertical>

          <InputVertical
            withLabel={FIELD_BEDROCK_AUTH_METHOD}
            title="认证方式"
            subDescription="选择 Glomi AI 如何与 Bedrock 进行认证。"
          >
            <InputSelectField name={FIELD_BEDROCK_AUTH_METHOD}>
              <InputSelect.Trigger />
              <InputSelect.Content>
                <InputSelect.Item
                  value={AUTH_METHOD_IAM}
                  description="推荐用于 AWS 环境"
                >
                  环境 IAM 角色
                </InputSelect.Item>
                <InputSelect.Item
                  value={AUTH_METHOD_ACCESS_KEY}
                  description="用于非 AWS 环境"
                >
                  Access Key
                </InputSelect.Item>
                <InputSelect.Item
                  value={AUTH_METHOD_LONG_TERM_API_KEY}
                  description="用于非 AWS 环境"
                >
                  长期 API Key
                </InputSelect.Item>
              </InputSelect.Content>
            </InputSelectField>
          </InputVertical>
        </Section>
      </InputPadder>

      {authMethod === AUTH_METHOD_ACCESS_KEY && (
        <Card background="light" border="none" padding="sm">
          <Section gap={1}>
            <InputVertical
              withLabel={FIELD_AWS_ACCESS_KEY_ID}
              title="AWS Access Key ID"
            >
              <InputTypeInField
                name={FIELD_AWS_ACCESS_KEY_ID}
                placeholder="AKIAIOSFODNN7EXAMPLE"
              />
            </InputVertical>
            <InputVertical
              withLabel={FIELD_AWS_SECRET_ACCESS_KEY}
              title="AWS Secret Access Key"
            >
              <PasswordInputTypeInField
                name={FIELD_AWS_SECRET_ACCESS_KEY}
                placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
              />
            </InputVertical>
          </Section>
        </Card>
      )}

      {authMethod === AUTH_METHOD_IAM && (
        <InputPadder>
          <MessageCard
            variant="info"
            title="Glomi AI 将使用当前运行环境绑定的 IAM 角色进行认证。"
          />
        </InputPadder>
      )}

      {authMethod === AUTH_METHOD_LONG_TERM_API_KEY && (
        <Card background="light" border="none" padding="sm">
          <Section gap={0.5}>
            <InputVertical
              withLabel={FIELD_AWS_BEARER_TOKEN_BEDROCK}
              title="长期 API Key"
            >
              <PasswordInputTypeInField
                name={FIELD_AWS_BEARER_TOKEN_BEDROCK}
                placeholder="你的长期 API Key"
              />
            </InputVertical>
          </Section>
        </Card>
      )}

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField />
        </>
      )}

      <InputDivider />
      <ModelSelectionField
        shouldShowAutoUpdateToggle={false}
        onRefetch={isFetchDisabled ? undefined : handleFetchModels}
      />

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </>
  );
}

export default function BedrockModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues: BedrockModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.BEDROCK,
      existingLlmProvider
    ),
    custom_config: {
      AWS_REGION_NAME:
        (existingLlmProvider?.custom_config?.AWS_REGION_NAME as string) ?? "",
      BEDROCK_AUTH_METHOD:
        (existingLlmProvider?.custom_config?.BEDROCK_AUTH_METHOD as string) ??
        AUTH_METHOD_ACCESS_KEY,
      AWS_ACCESS_KEY_ID:
        (existingLlmProvider?.custom_config?.AWS_ACCESS_KEY_ID as string) ?? "",
      AWS_SECRET_ACCESS_KEY:
        (existingLlmProvider?.custom_config?.AWS_SECRET_ACCESS_KEY as string) ??
        "",
      AWS_BEARER_TOKEN_BEDROCK:
        (existingLlmProvider?.custom_config
          ?.AWS_BEARER_TOKEN_BEDROCK as string) ?? "",
    },
  } as BedrockModalValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
    extra: {
      custom_config: Yup.object({
        AWS_REGION_NAME: Yup.string().required("请选择 AWS 区域"),
      }),
    },
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.BEDROCK}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        const filteredCustomConfig = Object.fromEntries(
          Object.entries(values.custom_config || {}).filter(([, v]) => v !== "")
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
          providerName: LLMProviderName.BEDROCK,
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
      <BedrockModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
