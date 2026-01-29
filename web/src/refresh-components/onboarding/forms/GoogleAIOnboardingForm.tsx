import React, { useMemo } from "react";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import Separator from "@/refresh-components/Separator";
import {
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";
import {
  OnboardingFormWrapper,
  OnboardingFormChildProps,
} from "./OnboardingFormWrapper";
import { OnboardingActions, OnboardingState } from "../types";
import { buildInitialValues } from "../components/llmConnectionHelpers";
import ConnectionProviderIcon from "@/refresh-components/ConnectionProviderIcon";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";

// Field name constants
const FIELD_API_KEY = "api_key";
const FIELD_DEFAULT_MODEL_NAME = "default_model_name";

const DEFAULT_DEFAULT_MODEL_NAME = "gemini-3-pro-preview";

interface GoogleAIOnboardingFormProps {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface GoogleAIFormValues {
  name: string;
  provider: string;
  api_key: string;
  api_key_changed: boolean;
  default_model_name: string;
  model_configurations: any[];
  groups: number[];
  is_public: boolean;
}

function GoogleAIFormFields(
  props: OnboardingFormChildProps<GoogleAIFormValues>
) {
  const { apiStatus, showApiMessage, errorMessage, modelOptions, disabled } =
    props;

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
                      <InlineExternalLink href="https://aistudio.google.com/apikey">
                        API key
                      </InlineExternalLink>
                      {" from Google AI Studio to access Gemini models."}
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
                  loading: "Checking API key with Google AI Studio...",
                  success: "API key valid.",
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
                disabled={disabled || modelOptions.length === 0}
                onBlur={field.onBlur}
                placeholder="Select a model"
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: "This model will be used by Onyx by default.",
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />
    </>
  );
}

export function GoogleAIOnboardingForm({
  llmDescriptor,
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
}: GoogleAIOnboardingFormProps) {
  const initialValues = useMemo(
    (): GoogleAIFormValues => ({
      ...buildInitialValues(),
      name: llmDescriptor.name,
      provider: llmDescriptor.name,
      default_model_name: DEFAULT_DEFAULT_MODEL_NAME,
    }),
    [llmDescriptor.name]
  );

  const validationSchema = Yup.object().shape({
    [FIELD_API_KEY]: Yup.string().required("API Key is required"),
    [FIELD_DEFAULT_MODEL_NAME]: Yup.string().required("Model name is required"),
  });

  const icon = () => (
    <ConnectionProviderIcon
      icon={<ProviderIcon provider={llmDescriptor.name} size={24} />}
    />
  );

  // Enable auto mode if user keeps the recommended default model
  const transformValues = (
    values: GoogleAIFormValues,
    modelConfigurations: ModelConfiguration[]
  ) => ({
    ...values,
    model_configurations: modelConfigurations,
    is_auto_mode: values.default_model_name === DEFAULT_DEFAULT_MODEL_NAME,
  });

  return (
    <OnboardingFormWrapper<GoogleAIFormValues>
      icon={icon}
      title="Set up Gemini"
      description="Connect to Google AI Studio and set up your Gemini models."
      llmDescriptor={llmDescriptor}
      onboardingState={onboardingState}
      onboardingActions={onboardingActions}
      open={open}
      onOpenChange={onOpenChange}
      initialValues={initialValues}
      validationSchema={validationSchema}
      transformValues={transformValues}
    >
      {(props) => <GoogleAIFormFields {...props} />}
    </OnboardingFormWrapper>
  );
}
