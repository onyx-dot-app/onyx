"use client";

import { useState, useEffect } from "react";
import { useSWRConfig } from "swr";
import { Formik, FormikProps } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import * as InputLayouts from "@/layouts/input-layouts";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import {
  LLMProviderFormProps,
  LLMProviderView,
  ModelConfiguration,
} from "@/interfaces/llm";
import * as Yup from "yup";
import { useWellKnownLLMProvider } from "@/hooks/useLLMProviders";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  buildOnboardingInitialValues,
  BaseLLMFormValues,
} from "@/sections/modals/llmConfig/utils";
import {
  submitLLMProvider,
  submitOnboardingProvider,
} from "@/sections/modals/llmConfig/svc";
import {
  ModelsField,
  DisplayNameField,
  FieldSeparator,
  FieldWrapper,
  ModelsAccessField,
  SingleDefaultModelField,
  LLMConfigurationModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { fetchBedrockModels } from "@/app/admin/configuration/llm/utils";
import { Card } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { SvgAlertCircle } from "@opal/icons";
import { Content } from "@opal/layouts";
import { toast } from "@/hooks/useToast";
import useOnMount from "@/hooks/useOnMount";

const BEDROCK_PROVIDER_NAME = "bedrock";
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
  formikProps: FormikProps<BedrockModalValues>;
  existingLlmProvider: LLMProviderView | undefined;
  fetchedModels: ModelConfiguration[];
  setFetchedModels: (models: ModelConfiguration[]) => void;
  modelConfigurations: ModelConfiguration[];
  isTesting: boolean;
  onClose: () => void;
  isOnboarding: boolean;
}

function BedrockModalInternals({
  formikProps,
  existingLlmProvider,
  fetchedModels,
  setFetchedModels,
  modelConfigurations,
  isTesting,
  onClose,
  isOnboarding,
}: BedrockModalInternalsProps) {
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

  const currentModels =
    fetchedModels.length > 0
      ? fetchedModels
      : existingLlmProvider?.model_configurations || modelConfigurations;

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
      provider_name: existingLlmProvider?.name,
    });
    if (error) {
      throw new Error(error);
    }
    setFetchedModels(models);
  };

  // Auto-fetch models on initial load when editing an existing provider
  useOnMount(() => {
    if (existingLlmProvider && !isFetchDisabled) {
      handleFetchModels().catch((err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to fetch models"
        );
      });
    }
  });

  return (
    <LLMConfigurationModalWrapper
      providerEndpoint={BEDROCK_PROVIDER_NAME}
      existingProviderName={existingLlmProvider?.name}
      onClose={onClose}
      isFormValid={formikProps.isValid}
      isDirty={formikProps.dirty}
      isTesting={isTesting}
      isSubmitting={formikProps.isSubmitting}
    >
      <FieldWrapper>
        <Section gap={1}>
          <InputLayouts.Vertical
            name={FIELD_AWS_REGION_NAME}
            title="AWS Region"
            subDescription="Region where your Amazon Bedrock models are hosted."
          >
            <InputSelectField name={FIELD_AWS_REGION_NAME}>
              <InputSelect.Trigger placeholder="Select a region" />
              <InputSelect.Content>
                {AWS_REGION_OPTIONS.map((option) => (
                  <InputSelect.Item key={option.value} value={option.value}>
                    {option.name}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelectField>
          </InputLayouts.Vertical>

          <InputLayouts.Vertical
            name={FIELD_BEDROCK_AUTH_METHOD}
            title="Authentication Method"
            subDescription="Choose how Onyx should authenticate with Bedrock."
          >
            <InputSelect
              value={authMethod || AUTH_METHOD_ACCESS_KEY}
              onValueChange={(value) =>
                formikProps.setFieldValue(FIELD_BEDROCK_AUTH_METHOD, value)
              }
            >
              <InputSelect.Trigger defaultValue={AUTH_METHOD_IAM} />
              <InputSelect.Content>
                <InputSelect.Item
                  value={AUTH_METHOD_IAM}
                  description="Recommended for AWS environments"
                >
                  Environment IAM Role
                </InputSelect.Item>
                <InputSelect.Item
                  value={AUTH_METHOD_ACCESS_KEY}
                  description="For non-AWS environments"
                >
                  Access Key
                </InputSelect.Item>
                <InputSelect.Item
                  value={AUTH_METHOD_LONG_TERM_API_KEY}
                  description="For non-AWS environments"
                >
                  Long-term API Key
                </InputSelect.Item>
              </InputSelect.Content>
            </InputSelect>
          </InputLayouts.Vertical>
        </Section>
      </FieldWrapper>

      {authMethod === AUTH_METHOD_ACCESS_KEY && (
        <Card backgroundVariant="light" borderVariant="none" sizeVariant="lg">
          <Section gap={1}>
            <InputLayouts.Vertical
              name={FIELD_AWS_ACCESS_KEY_ID}
              title="AWS Access Key ID"
            >
              <InputTypeInField
                name={FIELD_AWS_ACCESS_KEY_ID}
                placeholder="AKIAIOSFODNN7EXAMPLE"
              />
            </InputLayouts.Vertical>
            <InputLayouts.Vertical
              name={FIELD_AWS_SECRET_ACCESS_KEY}
              title="AWS Secret Access Key"
            >
              <PasswordInputTypeInField
                name={FIELD_AWS_SECRET_ACCESS_KEY}
                placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
              />
            </InputLayouts.Vertical>
          </Section>
        </Card>
      )}

      {authMethod === AUTH_METHOD_IAM && (
        <FieldWrapper>
          <Card backgroundVariant="none" borderVariant="solid">
            <Content
              icon={SvgAlertCircle}
              title="Onyx will use the IAM role attached to the environment it’s running in to authenticate."
              variant="body"
              sizePreset="main-ui"
            />
          </Card>
        </FieldWrapper>
      )}

      {authMethod === AUTH_METHOD_LONG_TERM_API_KEY && (
        <Card backgroundVariant="light" borderVariant="none" sizeVariant="lg">
          <Section gap={0.5}>
            <InputLayouts.Vertical
              name={FIELD_AWS_BEARER_TOKEN_BEDROCK}
              title="Long-term API Key"
            >
              <PasswordInputTypeInField
                name={FIELD_AWS_BEARER_TOKEN_BEDROCK}
                placeholder="Your long-term API key"
              />
            </InputLayouts.Vertical>
          </Section>
        </Card>
      )}

      {!isOnboarding && (
        <>
          <FieldSeparator />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <FieldSeparator />

      {isOnboarding ? (
        <SingleDefaultModelField placeholder="E.g. us.anthropic.claude-sonnet-4-5-v1" />
      ) : (
        <ModelsField
          modelConfigurations={currentModels}
          formikProps={formikProps}
          recommendedDefaultModel={null}
          shouldShowAutoUpdateToggle={false}
          onRefetch={isFetchDisabled ? undefined : handleFetchModels}
        />
      )}

      {!isOnboarding && (
        <>
          <FieldSeparator />
          <ModelsAccessField formikProps={formikProps} />
        </>
      )}
    </LLMConfigurationModalWrapper>
  );
}

export default function BedrockModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  open,
  onOpenChange,
  defaultModelName,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);
  const [isTesting, setIsTesting] = useState(false);
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(
    BEDROCK_PROVIDER_NAME
  );

  if (open === false) return null;

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues: BedrockModalValues = isOnboarding
    ? ({
        ...buildOnboardingInitialValues(),
        name: BEDROCK_PROVIDER_NAME,
        provider: BEDROCK_PROVIDER_NAME,
        default_model_name: "",
        custom_config: {
          AWS_REGION_NAME: "",
          BEDROCK_AUTH_METHOD: "access_key",
          AWS_ACCESS_KEY_ID: "",
          AWS_SECRET_ACCESS_KEY: "",
          AWS_BEARER_TOKEN_BEDROCK: "",
        },
      } as BedrockModalValues)
    : {
        ...buildDefaultInitialValues(
          existingLlmProvider,
          modelConfigurations,
          defaultModelName
        ),
        custom_config: {
          AWS_REGION_NAME:
            (existingLlmProvider?.custom_config?.AWS_REGION_NAME as string) ??
            "",
          BEDROCK_AUTH_METHOD:
            (existingLlmProvider?.custom_config
              ?.BEDROCK_AUTH_METHOD as string) ?? "access_key",
          AWS_ACCESS_KEY_ID:
            (existingLlmProvider?.custom_config?.AWS_ACCESS_KEY_ID as string) ??
            "",
          AWS_SECRET_ACCESS_KEY:
            (existingLlmProvider?.custom_config
              ?.AWS_SECRET_ACCESS_KEY as string) ?? "",
          AWS_BEARER_TOKEN_BEDROCK:
            (existingLlmProvider?.custom_config
              ?.AWS_BEARER_TOKEN_BEDROCK as string) ?? "",
        },
      };

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        default_model_name: Yup.string().required("Model name is required"),
        custom_config: Yup.object({
          AWS_REGION_NAME: Yup.string().required("AWS Region is required"),
        }),
      })
    : buildDefaultValidationSchema().shape({
        custom_config: Yup.object({
          AWS_REGION_NAME: Yup.string().required("AWS Region is required"),
        }),
      });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount={true}
      onSubmit={async (values, { setSubmitting }) => {
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

        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            fetchedModels.length > 0 ? fetchedModels : [];

          await submitOnboardingProvider({
            providerName: BEDROCK_PROVIDER_NAME,
            payload: {
              ...submitValues,
              model_configurations: modelConfigsToUse,
            },
            onboardingState,
            onboardingActions,
            isCustomProvider: false,
            onClose,
            setIsSubmitting: setSubmitting,
          });
        } else {
          await submitLLMProvider({
            providerName: BEDROCK_PROVIDER_NAME,
            values: submitValues,
            initialValues,
            modelConfigurations:
              fetchedModels.length > 0 ? fetchedModels : modelConfigurations,
            existingLlmProvider,
            shouldMarkAsDefault,
            setIsTesting,
            mutate,
            onClose,
            setSubmitting,
          });
        }
      }}
    >
      {(formikProps) => (
        <BedrockModalInternals
          formikProps={formikProps}
          existingLlmProvider={existingLlmProvider}
          fetchedModels={fetchedModels}
          setFetchedModels={setFetchedModels}
          modelConfigurations={modelConfigurations}
          isTesting={isTesting}
          onClose={onClose}
          isOnboarding={isOnboarding}
        />
      )}
    </Formik>
  );
}
