import React, { useMemo } from "react";
import * as Yup from "yup";
import { FormikProps } from "formik";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import Separator from "@/refresh-components/Separator";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import {
  OnboardingFormWrapper,
  useOnboardingFormContext,
} from "./OnboardingFormWrapper";
import { OnboardingActions, OnboardingState } from "../types";
import { buildInitialValues } from "../components/llmConnectionHelpers";
import { MODAL_CONTENT_MAP } from "../constants";
import LLMConnectionIcons from "../components/LLMConnectionIcons";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";
import {
  isValidAzureTargetUri,
  parseAzureTargetUri,
} from "@/lib/azureTargetUri";

interface AzureOnboardingFormProps {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface AzureFormValues {
  name: string;
  provider: string;
  api_key: string;
  api_key_changed: boolean;
  api_base: string;
  api_version: string;
  deployment_name: string;
  target_uri: string;
  default_model_name: string;
  model_configurations: any[];
  groups: number[];
  is_public: boolean;
}

function AzureFormFields({
  formikProps,
}: {
  formikProps: FormikProps<AzureFormValues>;
}) {
  const {
    apiStatus,
    showApiMessage,
    errorMessage,
    modelOptions,
    disabled,
    llmDescriptor,
  } = useOnboardingFormContext();

  const modalContent = MODAL_CONTENT_MAP[llmDescriptor?.name ?? ""];

  return (
    <>
      <FormikField<string>
        name="target_uri"
        render={(field, helper, meta, state) => (
          <FormField name="target_uri" state={state} className="w-full">
            <FormField.Label>Target URI</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                placeholder="https://your-resource.cognitiveservices.azure.com/openai/deployments/deployment-name/chat/completions?api-version=2025-01-01-preview"
                showClearButton={false}
                disabled={disabled}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: (
                  <>
                    Paste your endpoint target URI from{" "}
                    <a
                      href="https://oai.azure.com"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline"
                    >
                      Azure OpenAI
                    </a>{" "}
                    (including API endpoint base, deployment name, and API
                    version).
                  </>
                ),
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />

      <FormikField<string>
        name="api_key"
        render={(field, helper, meta, state) => (
          <FormField name="api_key" state={state} className="w-full">
            <FormField.Label>API Key</FormField.Label>
            <FormField.Control>
              <PasswordInputTypeIn
                {...field}
                placeholder=""
                error={apiStatus === "error"}
                showClearButton={false}
                disabled={disabled || !formikProps.values.target_uri?.trim()}
              />
            </FormField.Control>
            {!showApiMessage && (
              <FormField.Message
                messages={{
                  idle:
                    modalContent?.field_metadata?.api_key ??
                    "Paste your API key from Azure OpenAI.",
                  error: meta.error,
                }}
              />
            )}
            {showApiMessage && (
              <FormField.APIMessage
                state={apiStatus}
                messages={{
                  loading: `Checking API key with ${
                    modalContent?.display_name ?? "Azure OpenAI"
                  }...`,
                  success: "API key valid. Your available models updated.",
                  error: errorMessage || "Invalid API key",
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
                disabled={disabled}
                onBlur={field.onBlur}
                placeholder="Select or type a model name"
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: modalContent?.field_metadata?.default_model_name,
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />
    </>
  );
}

export function AzureOnboardingForm({
  llmDescriptor,
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
}: AzureOnboardingFormProps) {
  const initialValues = useMemo(
    () => buildInitialValues(llmDescriptor, false) as AzureFormValues,
    [llmDescriptor]
  );

  const validationSchema = Yup.object().shape({
    api_key: Yup.string().required("API Key is required"),
    target_uri: Yup.string()
      .required("Target URI is required")
      .test(
        "valid-target-uri",
        "Target URI must be a valid URL with api-version query parameter and either a deployment name in the path (/openai/deployments/{name}/...) or /openai/responses for realtime",
        (value) => (value ? isValidAzureTargetUri(value) : false)
      ),
    default_model_name: Yup.string().required("Model name is required"),
  });

  const icon = () => (
    <LLMConnectionIcons
      icon={<ProviderIcon provider={llmDescriptor.name} size={24} />}
    />
  );

  return (
    <OnboardingFormWrapper<AzureFormValues>
      icon={icon}
      title={`Set up ${llmDescriptor.title}`}
      description={MODAL_CONTENT_MAP[llmDescriptor.name]?.description}
      llmDescriptor={llmDescriptor}
      onboardingState={onboardingState}
      onboardingActions={onboardingActions}
      open={open}
      onOpenChange={onOpenChange}
      initialValues={initialValues}
      validationSchema={validationSchema}
      transformValues={(values, fetchedModels) => {
        // Parse the target URI to extract api_base, api_version, and deployment_name
        let finalValues = { ...values };
        if (values.target_uri) {
          try {
            const { url, apiVersion, deploymentName } = parseAzureTargetUri(
              values.target_uri
            );
            finalValues.api_base = url.origin;
            finalValues.api_version = apiVersion;
            if (deploymentName) {
              finalValues.deployment_name = deploymentName;
            }
          } catch (error) {
            console.error("Failed to parse target_uri:", error);
          }
        }

        return {
          ...finalValues,
          model_configurations: fetchedModels,
        };
      }}
    >
      {(formikProps) => <AzureFormFields formikProps={formikProps} />}
    </OnboardingFormWrapper>
  );
}
