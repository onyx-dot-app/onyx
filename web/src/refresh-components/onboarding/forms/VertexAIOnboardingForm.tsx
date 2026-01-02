import React, { useMemo } from "react";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import InputFile from "@/refresh-components/inputs/InputFile";
import Separator from "@/refresh-components/Separator";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn, noProp } from "@/lib/utils";
import { SvgRefreshCw } from "@opal/icons";
import {
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";
import {
  OnboardingFormWrapper,
  OnboardingFormChildProps,
} from "./OnboardingFormWrapper";
import { OnboardingActions, OnboardingState } from "../types";
import {
  buildInitialValues,
  testApiKeyHelper,
} from "../components/llmConnectionHelpers";
import ConnectionProviderIcon from "@/refresh-components/ConnectionProviderIcon";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";

// Field name constants
const FIELD_DEFAULT_MODEL_NAME = "default_model_name";
const FIELD_VERTEX_CREDENTIALS = "custom_config.vertex_credentials";

const DEFAULT_DEFAULT_MODEL_NAME = "gemini-2.5-pro";

interface VertexAIOnboardingFormProps {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface VertexAIFormValues {
  name: string;
  provider: string;
  api_key_changed: boolean;
  default_model_name: string;
  model_configurations: any[];
  groups: number[];
  is_public: boolean;
  custom_config: {
    vertex_credentials: string;
  };
}

function VertexAIFormFields(
  props: OnboardingFormChildProps<VertexAIFormValues>
) {
  const {
    formikProps,
    apiStatus,
    setApiStatus,
    showApiMessage,
    setShowApiMessage,
    errorMessage,
    setErrorMessage,
    modelOptions,
    isFetchingModels,
    modelsApiStatus,
    modelsErrorMessage,
    showModelsApiErrorMessage,
    disabled,
    llmDescriptor,
  } = props;

  const handleFileInputChange = async (value: string) => {
    if (!llmDescriptor || !value) return;

    setApiStatus("loading");
    setShowApiMessage(true);

    const result = await testApiKeyHelper(
      llmDescriptor.name,
      formikProps.values,
      undefined,
      undefined,
      { vertex_credentials: value }
    );

    if (result.ok) {
      setApiStatus("success");
    } else {
      setErrorMessage(result.errorMessage);
      setApiStatus("error");
    }
  };

  return (
    <>
      <FormikField<string>
        name={FIELD_VERTEX_CREDENTIALS}
        render={(field, helper, meta, state) => (
          <FormField
            name={FIELD_VERTEX_CREDENTIALS}
            state={state}
            className="w-full"
          >
            <FormField.Label>Credentials File</FormField.Label>
            <FormField.Control>
              <InputFile
                setValue={(value) => helper.setValue(value)}
                onValueSet={handleFileInputChange}
                error={apiStatus === "error"}
                onBlur={(e) => {
                  field.onBlur(e);
                  if (field.value) {
                    handleFileInputChange(field.value);
                  }
                }}
                showClearButton={true}
                disabled={disabled}
              />
            </FormField.Control>
            {!showApiMessage && (
              <FormField.Message
                messages={{
                  idle: (
                    <>
                      {"Paste your "}
                      <InlineExternalLink href="https://console.cloud.google.com/projectselector2/iam-admin/serviceaccounts?supportedpurview=project">
                        service account credentials
                      </InlineExternalLink>
                      {" from Google Cloud Vertex AI."}
                    </>
                  ),
                  error: meta.error,
                }}
              />
            )}
            {showApiMessage && (
              <FormField.APIMessage
                state={apiStatus}
                messages={{
                  loading: "Verifying credentials with Vertex AI...",
                  success: "Credentials valid. Your available models updated.",
                  error: errorMessage || "Invalid credentials",
                }}
              />
            )}
          </FormField>
        )}
      />

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
                onBlur={field.onBlur}
                placeholder="Select a model"
              />
            </FormField.Control>
            {!showModelsApiErrorMessage && (
              <FormField.Message
                messages={{
                  idle: "This model will be used by Onyx by default.",
                  error: meta.error,
                }}
              />
            )}
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
          </FormField>
        )}
      />
    </>
  );
}

export function VertexAIOnboardingForm({
  llmDescriptor,
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
}: VertexAIOnboardingFormProps) {
  const initialValues = useMemo(
    (): VertexAIFormValues => ({
      ...buildInitialValues(),
      name: llmDescriptor.name,
      provider: llmDescriptor.name,
      custom_config: {
        vertex_credentials: "",
      },
      default_model_name: DEFAULT_DEFAULT_MODEL_NAME,
    }),
    [llmDescriptor.name]
  );

  const validationSchema = Yup.object().shape({
    [FIELD_DEFAULT_MODEL_NAME]: Yup.string().required("Model name is required"),
    custom_config: Yup.object().shape({
      vertex_credentials: Yup.string().required("Credentials file is required"),
    }),
  });

  const icon = () => (
    <ConnectionProviderIcon
      icon={<ProviderIcon provider={llmDescriptor.name} size={24} />}
    />
  );

  // Enable auto mode if user keeps the recommended default model
  const transformValues = (
    values: VertexAIFormValues,
    modelConfigurations: ModelConfiguration[]
  ) => ({
    ...values,
    model_configurations: modelConfigurations,
    is_auto_mode: values.default_model_name === DEFAULT_DEFAULT_MODEL_NAME,
  });

  return (
    <OnboardingFormWrapper<VertexAIFormValues>
      icon={icon}
      title="Set up Gemini"
      description="Connect to Google Cloud Vertex AI and set up your Gemini models."
      llmDescriptor={llmDescriptor}
      onboardingState={onboardingState}
      onboardingActions={onboardingActions}
      open={open}
      onOpenChange={onOpenChange}
      initialValues={initialValues}
      validationSchema={validationSchema}
      transformValues={transformValues}
    >
      {(props) => <VertexAIFormFields {...props} />}
    </OnboardingFormWrapper>
  );
}
