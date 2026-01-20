"use client";

import { useMemo } from "react";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import Separator from "@/refresh-components/Separator";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import {
  OnboardingFormWrapper,
  OnboardingFormChildProps,
} from "./OnboardingFormWrapper";
import { OnboardingActions, OnboardingState } from "../types";
import { buildInitialValues } from "../components/llmConnectionHelpers";
import ConnectionProviderIcon from "@/refresh-components/ConnectionProviderIcon";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";

// Field name constants
const FIELD_API_BASE = "api_base";
const FIELD_DEFAULT_MODEL_NAME = "default_model_name";

// Default AgentGateway endpoint
const AGENT_GATEWAY_DEFAULT_URL = "http://52.147.214.252:8080/gemini";

// Default available models
const AGENT_GATEWAY_MODELS = [
  { label: "Gemini 2.5 Flash", value: "gemini-2.5-flash" },
  { label: "Gemini 2.5 Pro", value: "gemini-2.5-pro" },
];

interface AgentGatewayOnboardingFormProps {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface AgentGatewayFormValues {
  name: string;
  provider: string;
  api_base: string;
  api_key_changed: boolean;
  default_model_name: string;
  model_configurations: any[];
  groups: number[];
  is_public: boolean;
}

function AgentGatewayFormFields(
  props: OnboardingFormChildProps<AgentGatewayFormValues>
) {
  const { formikProps, apiStatus, showApiMessage, errorMessage, disabled } =
    props;

  // Build model options from llmDescriptor or use defaults
  const modelOptions = useMemo(() => {
    return AGENT_GATEWAY_MODELS;
  }, []);

  return (
    <div className="flex flex-col gap-4 w-full">
      <FormikField<string>
        name={FIELD_API_BASE}
        render={(field, helper, meta, state) => (
          <FormField name={FIELD_API_BASE} state={state} className="w-full">
            <FormField.Label>API Base URL</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                placeholder={AGENT_GATEWAY_DEFAULT_URL}
                error={apiStatus === "error"}
                showClearButton={false}
                disabled={disabled}
              />
            </FormField.Control>
            {showApiMessage && (
              <FormField.APIMessage
                state={apiStatus}
                messages={{
                  loading: "Checking connection to AgentGateway...",
                  success: "Connected successfully.",
                  error: errorMessage || "Failed to connect",
                }}
              />
            )}
            {!showApiMessage && (
              <FormField.Message
                messages={{
                  idle: "Your AgentGateway API endpoint URL.",
                  error: meta.error,
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
                disabled={disabled}
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
    </div>
  );
}

export function AgentGatewayOnboardingForm({
  llmDescriptor,
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
}: AgentGatewayOnboardingFormProps) {
  const initialValues = useMemo(
    (): AgentGatewayFormValues => ({
      ...buildInitialValues(),
      name: llmDescriptor.name,
      provider: llmDescriptor.name,
      api_base: AGENT_GATEWAY_DEFAULT_URL,
      default_model_name: "gemini-2.5-flash",
    }),
    [llmDescriptor.name]
  );

  const validationSchema = useMemo(() => {
    return Yup.object().shape({
      [FIELD_API_BASE]: Yup.string().required("API Base URL is required"),
      [FIELD_DEFAULT_MODEL_NAME]: Yup.string().required(
        "Model name is required"
      ),
    });
  }, []);

  const icon = () => (
    <ConnectionProviderIcon
      icon={<ProviderIcon provider={llmDescriptor.name} size={24} />}
    />
  );

  // Build model configurations for submission
  const modelConfigurations = AGENT_GATEWAY_MODELS.map((model) => ({
    name: model.value,
    is_visible: true,
    max_input_tokens: model.value.includes("pro") ? 2000000 : 1000000,
    supports_image_input: true,
  }));

  return (
    <OnboardingFormWrapper<AgentGatewayFormValues>
      icon={icon}
      title="Set up AgentGateway"
      description="Connect to your AgentGateway LLM proxy."
      llmDescriptor={llmDescriptor}
      onboardingState={onboardingState}
      onboardingActions={onboardingActions}
      open={open}
      onOpenChange={onOpenChange}
      initialValues={initialValues}
      validationSchema={validationSchema}
      transformValues={(values) => {
        return {
          ...values,
          model_configurations: modelConfigurations,
        };
      }}
    >
      {(props) => <AgentGatewayFormFields {...props} />}
    </OnboardingFormWrapper>
  );
}
