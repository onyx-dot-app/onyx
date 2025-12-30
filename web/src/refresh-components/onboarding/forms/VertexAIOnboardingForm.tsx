import React, { useMemo } from "react";
import * as Yup from "yup";
import { FormikProps } from "formik";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import InputFile from "@/refresh-components/inputs/InputFile";
import Separator from "@/refresh-components/Separator";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn, noProp } from "@/lib/utils";
import { SvgRefreshCw } from "@opal/icons";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import {
  OnboardingFormWrapper,
  useOnboardingFormContext,
} from "./OnboardingFormWrapper";
import { OnboardingActions, OnboardingState } from "../types";
import {
  buildInitialValues,
  testApiKeyHelper,
} from "../components/llmConnectionHelpers";
import LLMConnectionIcons from "../components/LLMConnectionIcons";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";

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

function VertexAIFormFields({
  formikProps,
}: {
  formikProps: FormikProps<VertexAIFormValues>;
}) {
  const {
    apiStatus,
    setApiStatus,
    showApiMessage,
    setShowApiMessage,
    errorMessage,
    setErrorMessage,
    modelOptions,
    canFetchModels,
    isFetchingModels,
    handleFetchModels,
    modelsApiStatus,
    modelsErrorMessage,
    showModelsApiErrorMessage,
    disabled,
    llmDescriptor,
  } = useOnboardingFormContext();

  const handleFileInputChange = async (value: string) => {
    if (!llmDescriptor || !value) return;

    setApiStatus("loading");
    setShowApiMessage(true);

    const result = await testApiKeyHelper(
      llmDescriptor,
      formikProps.initialValues,
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
        name="custom_config.vertex_credentials"
        render={(field, helper, meta, state) => (
          <FormField
            name="custom_config.vertex_credentials"
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
        name="default_model_name"
        render={(field, helper, meta, state) => (
          <FormField name="default_model_name" state={state} className="w-full">
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
                  canFetchModels ? (
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
                        handleFetchModels();
                      })}
                      tooltip="Fetch available models"
                      disabled={disabled || isFetchingModels}
                    />
                  ) : undefined
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
  const initialValues = useMemo(() => {
    const base = buildInitialValues(llmDescriptor, false);
    return {
      ...base,
      custom_config: {
        vertex_credentials: "",
      },
    } as VertexAIFormValues;
  }, [llmDescriptor]);

  const validationSchema = Yup.object().shape({
    default_model_name: Yup.string().required("Model name is required"),
    custom_config: Yup.object().shape({
      vertex_credentials: Yup.string().required("Credentials file is required"),
    }),
  });

  const icon = () => (
    <LLMConnectionIcons
      icon={<ProviderIcon provider={llmDescriptor.name} size={24} />}
    />
  );

  return (
    <OnboardingFormWrapper<VertexAIFormValues>
      icon={icon}
      title={`Set up ${llmDescriptor.title}`}
      description="Connect to Google Cloud Vertex AI and set up your Gemini models."
      llmDescriptor={llmDescriptor}
      onboardingState={onboardingState}
      onboardingActions={onboardingActions}
      open={open}
      onOpenChange={onOpenChange}
      initialValues={initialValues}
      validationSchema={validationSchema}
    >
      {(formikProps) => <VertexAIFormFields formikProps={formikProps} />}
    </OnboardingFormWrapper>
  );
}
