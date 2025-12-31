import React, { useMemo } from "react";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Separator from "@/refresh-components/Separator";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn, noProp } from "@/lib/utils";
import { SvgAlertCircle, SvgRefreshCw } from "@opal/icons";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import {
  OnboardingFormWrapper,
  OnboardingFormChildProps,
} from "./OnboardingFormWrapper";
import { OnboardingActions, OnboardingState } from "../types";
import { buildInitialValues } from "../components/llmConnectionHelpers";
import ConnectionProviderIcon from "@/refresh-components/ConnectionProviderIcon";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";

// AWS Bedrock regions
const AWS_REGION_OPTIONS = [
  { label: "us-east-1", value: "us-east-1" },
  { label: "us-east-2", value: "us-east-2" },
  { label: "us-west-2", value: "us-west-2" },
  { label: "us-gov-east-1", value: "us-gov-east-1" },
  { label: "us-gov-west-1", value: "us-gov-west-1" },
  { label: "ap-northeast-1", value: "ap-northeast-1" },
  { label: "ap-south-1", value: "ap-south-1" },
  { label: "ap-southeast-1", value: "ap-southeast-1" },
  { label: "ap-southeast-2", value: "ap-southeast-2" },
  { label: "ap-east-1", value: "ap-east-1" },
  { label: "ca-central-1", value: "ca-central-1" },
  { label: "eu-central-1", value: "eu-central-1" },
  { label: "eu-west-2", value: "eu-west-2" },
];

// Auth method constants
const AUTH_METHOD_IAM = "iam";
const AUTH_METHOD_ACCESS_KEY = "access_key";
const AUTH_METHOD_LONG_TERM_API_KEY = "long_term_api_key";

// Field name constants
const FIELD_DEFAULT_MODEL_NAME = "default_model_name";
const FIELD_AWS_REGION_NAME = "custom_config.AWS_REGION_NAME";
const FIELD_BEDROCK_AUTH_METHOD = "custom_config.BEDROCK_AUTH_METHOD";
const FIELD_AWS_ACCESS_KEY_ID = "custom_config.AWS_ACCESS_KEY_ID";
const FIELD_AWS_SECRET_ACCESS_KEY = "custom_config.AWS_SECRET_ACCESS_KEY";
const FIELD_AWS_BEARER_TOKEN_BEDROCK = "custom_config.AWS_BEARER_TOKEN_BEDROCK";

interface BedrockOnboardingFormProps {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface BedrockFormValues {
  name: string;
  provider: string;
  api_key_changed: boolean;
  default_model_name: string;
  model_configurations: any[];
  groups: number[];
  is_public: boolean;
  custom_config: {
    AWS_REGION_NAME: string;
    BEDROCK_AUTH_METHOD: string;
    AWS_ACCESS_KEY_ID?: string;
    AWS_SECRET_ACCESS_KEY?: string;
    AWS_BEARER_TOKEN_BEDROCK?: string;
  };
}

function BedrockFormFields(props: OnboardingFormChildProps<BedrockFormValues>) {
  const {
    formikProps,
    apiStatus,
    showApiMessage,
    errorMessage,
    modelOptions,
    isFetchingModels,
    handleFetchModels,
    modelsApiStatus,
    modelsErrorMessage,
    showModelsApiErrorMessage,
    disabled,
  } = props;

  const authMethod =
    formikProps.values.custom_config?.BEDROCK_AUTH_METHOD ||
    AUTH_METHOD_ACCESS_KEY;

  // Check if auth credentials are complete for enabling fetch models
  const isAuthComplete =
    authMethod === AUTH_METHOD_IAM ||
    (authMethod === AUTH_METHOD_ACCESS_KEY &&
      formikProps.values.custom_config?.AWS_ACCESS_KEY_ID &&
      formikProps.values.custom_config?.AWS_SECRET_ACCESS_KEY) ||
    (authMethod === AUTH_METHOD_LONG_TERM_API_KEY &&
      formikProps.values.custom_config?.AWS_BEARER_TOKEN_BEDROCK);

  const isFetchDisabled =
    !formikProps.values.custom_config?.AWS_REGION_NAME || !isAuthComplete;

  return (
    <>
      <FormikField<string>
        name={FIELD_AWS_REGION_NAME}
        render={(field, helper, meta, state) => (
          <FormField
            name={FIELD_AWS_REGION_NAME}
            state={state}
            className="w-full"
          >
            <FormField.Label>AWS Region</FormField.Label>
            <FormField.Control>
              <InputSelect
                value={field.value ?? ""}
                onValueChange={(value) => helper.setValue(value)}
                disabled={disabled}
              >
                <InputSelect.Trigger onBlur={field.onBlur} />
                <InputSelect.Content>
                  {AWS_REGION_OPTIONS.map((opt) => (
                    <InputSelect.Item key={opt.value} value={opt.value}>
                      {opt.label}
                    </InputSelect.Item>
                  ))}
                </InputSelect.Content>
              </InputSelect>
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: "Region where your Amazon Bedrock models are hosted.",
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />

      <FormikField<string>
        name={FIELD_BEDROCK_AUTH_METHOD}
        render={(field, helper, meta, state) => (
          <FormField
            name={FIELD_BEDROCK_AUTH_METHOD}
            state={state}
            className="w-full"
          >
            <FormField.Label>Authentication Method</FormField.Label>
            <FormField.Control>
              <InputSelect
                value={authMethod}
                onValueChange={(value) => helper.setValue(value)}
                disabled={disabled}
              >
                <InputSelect.Trigger onBlur={field.onBlur} />
                <InputSelect.Content>
                  <InputSelect.Item value={AUTH_METHOD_IAM}>
                    IAM Role
                  </InputSelect.Item>
                  <InputSelect.Item value={AUTH_METHOD_ACCESS_KEY}>
                    Access Key
                  </InputSelect.Item>
                  <InputSelect.Item value={AUTH_METHOD_LONG_TERM_API_KEY}>
                    Long-term API Key
                  </InputSelect.Item>
                </InputSelect.Content>
              </InputSelect>
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: (
                  <>
                    {"See "}
                    <InlineExternalLink
                      href={`${DOCS_ADMINS_PATH}/ai_models/bedrock#authentication-methods`}
                    >
                      documentation
                    </InlineExternalLink>
                    {" for more instructions."}
                  </>
                ),
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />

      {authMethod === AUTH_METHOD_IAM && (
        <div className="flex gap-1 p-2 border border-border-01 rounded-12 bg-background-tint-01">
          <div className="p-1">
            <SvgAlertCircle className="h-4 w-4 stroke-text-03" />
          </div>
          <Text as="p" text04 mainUiBody>
            Onyx will use the IAM role attached to the environment it&apos;s
            running in to authenticate.
          </Text>
        </div>
      )}

      {authMethod === AUTH_METHOD_ACCESS_KEY && (
        <>
          <FormikField<string>
            name={FIELD_AWS_ACCESS_KEY_ID}
            render={(field, helper, meta, state) => (
              <FormField
                name={FIELD_AWS_ACCESS_KEY_ID}
                state={state}
                className="w-full"
              >
                <FormField.Label>AWS Access Key ID</FormField.Label>
                <FormField.Control>
                  <InputTypeIn
                    {...field}
                    placeholder="AKIAIOSFODNN7EXAMPLE"
                    showClearButton={false}
                    disabled={disabled}
                    error={apiStatus === "error"}
                  />
                </FormField.Control>
                <FormField.Message
                  messages={{
                    idle: "",
                    error: meta.error,
                  }}
                />
              </FormField>
            )}
          />
          <FormikField<string>
            name={FIELD_AWS_SECRET_ACCESS_KEY}
            render={(field, helper, meta, state) => (
              <FormField
                name={FIELD_AWS_SECRET_ACCESS_KEY}
                state={state}
                className="w-full"
              >
                <FormField.Label>AWS Secret Access Key</FormField.Label>
                <FormField.Control>
                  <PasswordInputTypeIn
                    {...field}
                    placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                    showClearButton={false}
                    disabled={disabled}
                    error={apiStatus === "error"}
                  />
                </FormField.Control>
                {showApiMessage && (
                  <FormField.APIMessage
                    state={apiStatus}
                    messages={{
                      loading: "Checking credentials...",
                      success: "Credentials valid.",
                      error: errorMessage || "Invalid credentials",
                    }}
                  />
                )}
                {!showApiMessage && (
                  <FormField.Message
                    messages={{
                      idle: "",
                      error: meta.error,
                    }}
                  />
                )}
              </FormField>
            )}
          />
        </>
      )}

      {authMethod === AUTH_METHOD_LONG_TERM_API_KEY && (
        <FormikField<string>
          name={FIELD_AWS_BEARER_TOKEN_BEDROCK}
          render={(field, helper, meta, state) => (
            <FormField
              name={FIELD_AWS_BEARER_TOKEN_BEDROCK}
              state={state}
              className="w-full"
            >
              <FormField.Label>AWS Bedrock Long-term API Key</FormField.Label>
              <FormField.Control>
                <PasswordInputTypeIn
                  {...field}
                  placeholder="Your long-term API key"
                  showClearButton={false}
                  disabled={disabled}
                  error={apiStatus === "error"}
                />
              </FormField.Control>
              {showApiMessage && (
                <FormField.APIMessage
                  state={apiStatus}
                  messages={{
                    loading: "Checking API key...",
                    success: "API key valid.",
                    error: errorMessage || "Invalid API key",
                  }}
                />
              )}
              {!showApiMessage && (
                <FormField.Message
                  messages={{
                    idle: "",
                    error: meta.error,
                  }}
                />
              )}
            </FormField>
          )}
        />
      )}

      <Separator className="my-0" />

      <FormikField<string>
        name={FIELD_DEFAULT_MODEL_NAME}
        render={(field, helper, meta, state) => (
          <FormField
            name={FIELD_DEFAULT_MODEL_NAME}
            state={state}
            className="w-full"
          >
            <FormField.Label>Default Model</FormField.Label>
            <FormField.Control>
              <InputComboBox
                value={field.value}
                onValueChange={(value) => helper.setValue(value)}
                onChange={(e) => helper.setValue(e.target.value)}
                options={modelOptions}
                disabled={
                  disabled || isFetchingModels || modelOptions.length === 0
                }
                rightSection={
                  <IconButton
                    internal
                    icon={({ className }) => (
                      <SvgRefreshCw
                        className={cn(
                          className,
                          isFetchingModels && "animate-spin"
                        )}
                      />
                    )}
                    onClick={noProp((e) => {
                      e.preventDefault();
                      if (!isFetchDisabled) {
                        handleFetchModels();
                      }
                    })}
                    tooltip={
                      isFetchDisabled
                        ? !formikProps.values.custom_config?.AWS_REGION_NAME
                          ? "Select an AWS region first"
                          : "Complete authentication first"
                        : "Fetch available models"
                    }
                    disabled={disabled || isFetchingModels || isFetchDisabled}
                  />
                }
                onBlur={field.onBlur}
                placeholder="Select a model"
              />
            </FormField.Control>
            {showModelsApiErrorMessage && (
              <FormField.APIMessage
                state={modelsApiStatus}
                messages={{
                  loading: "Fetching models...",
                  success: "Models fetched successfully.",
                  error: modelsErrorMessage || "Failed to fetch models",
                }}
              />
            )}
            {!showModelsApiErrorMessage && (
              <FormField.Message
                messages={{
                  error: meta.error,
                }}
              />
            )}
          </FormField>
        )}
      />
    </>
  );
}

export function BedrockOnboardingForm({
  llmDescriptor,
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
}: BedrockOnboardingFormProps) {
  const initialValues = useMemo(
    (): BedrockFormValues => ({
      ...buildInitialValues(),
      name: llmDescriptor.name,
      provider: llmDescriptor.name,
      custom_config: {
        AWS_REGION_NAME: "",
        BEDROCK_AUTH_METHOD: AUTH_METHOD_ACCESS_KEY,
        AWS_ACCESS_KEY_ID: "",
        AWS_SECRET_ACCESS_KEY: "",
        AWS_BEARER_TOKEN_BEDROCK: "",
      },
    }),
    [llmDescriptor.name]
  );

  const validationSchema = Yup.object().shape({
    [FIELD_DEFAULT_MODEL_NAME]: Yup.string().required("Model name is required"),
    custom_config: Yup.object().shape({
      AWS_REGION_NAME: Yup.string().required("AWS Region is required"),
      BEDROCK_AUTH_METHOD: Yup.string(),
      AWS_ACCESS_KEY_ID: Yup.string().when("BEDROCK_AUTH_METHOD", {
        is: AUTH_METHOD_ACCESS_KEY,
        then: (schema) => schema.required("AWS Access Key ID is required"),
        otherwise: (schema) => schema,
      }),
      AWS_SECRET_ACCESS_KEY: Yup.string().when("BEDROCK_AUTH_METHOD", {
        is: AUTH_METHOD_ACCESS_KEY,
        then: (schema) => schema.required("AWS Secret Access Key is required"),
        otherwise: (schema) => schema,
      }),
      AWS_BEARER_TOKEN_BEDROCK: Yup.string().when("BEDROCK_AUTH_METHOD", {
        is: AUTH_METHOD_LONG_TERM_API_KEY,
        then: (schema) => schema.required("Long-term API Key is required"),
        otherwise: (schema) => schema,
      }),
    }),
  });

  const icon = () => (
    <ConnectionProviderIcon
      icon={<ProviderIcon provider={llmDescriptor.name} size={24} />}
    />
  );

  return (
    <OnboardingFormWrapper<BedrockFormValues>
      icon={icon}
      title="Set up Amazon Bedrock"
      description="Connect to AWS and set up your Amazon Bedrock models."
      llmDescriptor={llmDescriptor}
      onboardingState={onboardingState}
      onboardingActions={onboardingActions}
      open={open}
      onOpenChange={onOpenChange}
      initialValues={initialValues}
      validationSchema={validationSchema}
      transformValues={(values, fetchedModels) => {
        // Filter out empty custom_config values
        const filteredCustomConfig = Object.fromEntries(
          Object.entries(values.custom_config || {}).filter(([, v]) => v !== "")
        );

        return {
          ...values,
          custom_config:
            Object.keys(filteredCustomConfig).length > 0
              ? filteredCustomConfig
              : undefined,
          model_configurations: fetchedModels,
        };
      }}
    >
      {(props) => <BedrockFormFields {...props} />}
    </OnboardingFormWrapper>
  );
}
