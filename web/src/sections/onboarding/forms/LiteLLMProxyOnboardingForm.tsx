"use client";

import { useMemo } from "react";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Separator from "@/refresh-components/Separator";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { cn, noProp } from "@/lib/utils";
import { SvgRefreshCw } from "@opal/icons";
import { WellKnownLLMProviderDescriptor } from "@/interfaces/llm";
import {
  OnboardingFormWrapper,
  OnboardingFormChildProps,
} from "./OnboardingFormWrapper";
import { OnboardingActions, OnboardingState } from "@/interfaces/onboarding";
import { buildInitialValues } from "../components/llmConnectionHelpers";
import ConnectionProviderIcon from "@/refresh-components/ConnectionProviderIcon";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";

const FIELD_API_KEY = "api_key";
const FIELD_API_BASE = "api_base";
const FIELD_DEFAULT_MODEL_NAME = "default_model_name";

interface LiteLLMProxyOnboardingFormProps {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface LiteLLMProxyFormValues {
  name: string;
  provider: string;
  api_key: string;
  api_base: string;
  api_key_changed: boolean;
  default_model_name: string;
  model_configurations: any[];
  groups: number[];
  is_public: boolean;
}

function LiteLLMProxyFormFields(
  props: OnboardingFormChildProps<LiteLLMProxyFormValues>
) {
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

  const handleApiKeyInteraction = () => {
    if (formikProps.values.api_key && formikProps.values.api_base) {
      handleFetchModels();
    }
  };

  return (
    <>
      <FormikField<string>
        name={FIELD_API_BASE}
        render={(field, _helper, meta, state) => (
          <FormField name={FIELD_API_BASE} state={state} className="w-full">
            <FormField.Label>API Base URL</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                placeholder="http://localhost:4000"
                variant={disabled ? "disabled" : undefined}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: "The base URL for your LiteLLM Proxy server.",
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />

      <FormikField<string>
        name={FIELD_API_KEY}
        render={(field, _helper, meta, state) => (
          <FormField name={FIELD_API_KEY} state={state} className="w-full">
            <FormField.Label>API Key</FormField.Label>
            <FormField.Control>
              <PasswordInputTypeIn
                {...field}
                placeholder=""
                error={apiStatus === "error"}
                showClearButton={false}
                disabled={disabled}
                onBlur={(e) => {
                  field.onBlur(e);
                  handleApiKeyInteraction();
                }}
              />
            </FormField.Control>
            {!showApiMessage && (
              <FormField.Message
                messages={{
                  idle: "Enter the API key for your LiteLLM Proxy.",
                  error: meta.error,
                }}
              />
            )}
            {showApiMessage && (
              <FormField.APIMessage
                state={apiStatus}
                messages={{
                  loading: "Checking API key with LiteLLM Proxy...",
                  success: "API key valid. Your available models updated.",
                  error: errorMessage || "Invalid API key",
                }}
              />
            )}
          </FormField>
        )}
      />

      <Separator className="py-0" />

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
                  <Disabled disabled={disabled || isFetchingModels}>
                    <Button
                      prominence="tertiary"
                      size="sm"
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
                    />
                  </Disabled>
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

export function LiteLLMProxyOnboardingForm({
  llmDescriptor,
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
}: LiteLLMProxyOnboardingFormProps) {
  const initialValues = useMemo(
    (): LiteLLMProxyFormValues => ({
      ...buildInitialValues(),
      name: llmDescriptor.name,
      provider: llmDescriptor.name,
      api_base: "http://localhost:4000",
    }),
    [llmDescriptor.name]
  );

  const validationSchema = Yup.object().shape({
    [FIELD_API_KEY]: Yup.string().required("API Key is required"),
    [FIELD_API_BASE]: Yup.string().required("API Base URL is required"),
    [FIELD_DEFAULT_MODEL_NAME]: Yup.string().required("Model name is required"),
  });

  const icon = () => (
    <ConnectionProviderIcon
      icon={<ProviderIcon provider={llmDescriptor.name} size={24} />}
    />
  );

  return (
    <OnboardingFormWrapper<LiteLLMProxyFormValues>
      icon={icon}
      title="Set up LiteLLM Proxy"
      description="Connect to your LiteLLM Proxy server and set up your models."
      llmDescriptor={llmDescriptor}
      onboardingState={onboardingState}
      onboardingActions={onboardingActions}
      open={open}
      onOpenChange={onOpenChange}
      initialValues={initialValues}
      validationSchema={validationSchema}
    >
      {(props) => <LiteLLMProxyFormFields {...props} />}
    </OnboardingFormWrapper>
  );
}
