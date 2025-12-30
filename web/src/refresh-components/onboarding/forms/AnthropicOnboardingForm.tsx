import React, { useMemo } from "react";
import * as Yup from "yup";
import { FormikProps } from "formik";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
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
import { buildInitialValues } from "../components/llmConnectionHelpers";
import LLMConnectionIcons from "../components/LLMConnectionIcons";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";

// Field name constants
const FIELD_API_KEY = "api_key";
const FIELD_DEFAULT_MODEL_NAME = "default_model_name";

interface AnthropicOnboardingFormProps {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface AnthropicFormValues {
  name: string;
  provider: string;
  api_key: string;
  api_key_changed: boolean;
  default_model_name: string;
  model_configurations: any[];
  groups: number[];
  is_public: boolean;
}

function AnthropicFormFields({
  formikProps,
}: {
  formikProps: FormikProps<AnthropicFormValues>;
}) {
  const {
    apiStatus,
    showApiMessage,
    errorMessage,
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

  return (
    <>
      <FormikField<string>
        name={FIELD_API_KEY}
        render={(field, helper, meta, state) => (
          <FormField name={FIELD_API_KEY} state={state} className="w-full">
            <FormField.Label>API Key</FormField.Label>
            <FormField.Control>
              <PasswordInputTypeIn
                {...field}
                placeholder=""
                error={apiStatus === "error"}
                showClearButton={false}
                disabled={disabled}
              />
            </FormField.Control>
            {!showApiMessage && (
              <FormField.Message
                messages={{
                  idle: (
                    <>
                      {"Paste your "}
                      <InlineExternalLink href="https://console.anthropic.com/dashboard">
                        API key
                      </InlineExternalLink>
                      {" from Anthropic to access your models."}
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
                  loading: "Checking API key with Anthropic...",
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

export function AnthropicOnboardingForm({
  llmDescriptor,
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
}: AnthropicOnboardingFormProps) {
  const initialValues = useMemo(
    (): AnthropicFormValues => ({
      ...buildInitialValues(),
      name: llmDescriptor.name,
      provider: llmDescriptor.name,
    }),
    [llmDescriptor.name]
  );

  const validationSchema = Yup.object().shape({
    [FIELD_API_KEY]: Yup.string().required("API Key is required"),
    [FIELD_DEFAULT_MODEL_NAME]: Yup.string().required("Model name is required"),
  });

  const icon = () => (
    <LLMConnectionIcons
      icon={<ProviderIcon provider={llmDescriptor.name} size={24} />}
    />
  );

  return (
    <OnboardingFormWrapper<AnthropicFormValues>
      icon={icon}
      title="Set up Claude"
      description="Connect to Anthropic and set up your Claude models."
      llmDescriptor={llmDescriptor}
      onboardingState={onboardingState}
      onboardingActions={onboardingActions}
      open={open}
      onOpenChange={onOpenChange}
      initialValues={initialValues}
      validationSchema={validationSchema}
    >
      {(formikProps) => <AnthropicFormFields formikProps={formikProps} />}
    </OnboardingFormWrapper>
  );
}
