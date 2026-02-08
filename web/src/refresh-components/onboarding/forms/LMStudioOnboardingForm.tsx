"use client";

import { useMemo, useEffect, useRef } from "react";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import Separator from "@/refresh-components/Separator";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn, noProp } from "@/lib/utils";
import { SvgRefreshCw } from "@opal/icons";
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
const FIELD_LM_STUDIO_API_KEY = "custom_config.LM_STUDIO_API_KEY";

const LM_STUDIO_DEFAULT_URL = "http://localhost:1234/v1";

interface LMStudioOnboardingFormProps {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface LMStudioFormValues {
  name: string;
  provider: string;
  api_base: string;
  api_key_changed: boolean;
  default_model_name: string;
  model_configurations: any[];
  groups: number[];
  is_public: boolean;
  custom_config: {
    LM_STUDIO_API_KEY?: string;
  };
}

function LMStudioFormFields(
  props: OnboardingFormChildProps<LMStudioFormValues>
) {
  const {
    formikProps,
    apiStatus,
    showApiMessage,
    errorMessage,
    setApiStatus,
    modelOptions,
    isFetchingModels,
    handleFetchModels,
    modelsApiStatus,
    modelsErrorMessage,
    showModelsApiErrorMessage,
    disabled,
  } = props;

  // Auto-fetch models on initial load and when api_base or API key changes
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!formikProps.values.api_base) return;

    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    debounceRef.current = setTimeout(() => {
      setApiStatus("loading");
      handleFetchModels();
    }, 500);

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [
    formikProps.values.api_base,
    formikProps.values.custom_config?.LM_STUDIO_API_KEY,
  ]);

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
                placeholder={LM_STUDIO_DEFAULT_URL}
                variant={
                  disabled
                    ? "disabled"
                    : apiStatus === "error"
                      ? "error"
                      : undefined
                }
                showClearButton={false}
              />
            </FormField.Control>
            {showApiMessage && (
              <FormField.APIMessage
                state={apiStatus}
                messages={{
                  loading: "Checking connection to LM Studio...",
                  success: "Connected successfully.",
                  error: errorMessage || "Failed to connect",
                }}
              />
            )}
            {!showApiMessage && (
              <FormField.Message
                messages={{
                  idle: "Your LM Studio server URL (default: http://localhost:1234/v1).",
                  error: meta.error,
                }}
              />
            )}
          </FormField>
        )}
      />

      <FormikField<string>
        name={FIELD_LM_STUDIO_API_KEY}
        render={(field, helper, meta, state) => (
          <FormField
            name={FIELD_LM_STUDIO_API_KEY}
            state={state}
            className="w-full"
          >
            <FormField.Label>API Key (Optional)</FormField.Label>
            <FormField.Control>
              <PasswordInputTypeIn
                {...field}
                placeholder=""
                disabled={disabled}
                error={false}
                showClearButton={false}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: "Optional API key if your LM Studio server requires authentication.",
                error: meta.error,
              }}
            />
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
                disabled={disabled || isFetchingModels}
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
                      handleFetchModels();
                    })}
                    tooltip="Fetch available models"
                    disabled={disabled || isFetchingModels}
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
                  idle: "This model will be used by Onyx by default.",
                  error: meta.error,
                }}
              />
            )}
          </FormField>
        )}
      />
    </div>
  );
}

export function LMStudioOnboardingForm({
  llmDescriptor,
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
}: LMStudioOnboardingFormProps) {
  const initialValues = useMemo(
    (): LMStudioFormValues => ({
      ...buildInitialValues(),
      name: llmDescriptor.name,
      provider: llmDescriptor.name,
      api_base: LM_STUDIO_DEFAULT_URL,
      custom_config: {
        LM_STUDIO_API_KEY: "",
      },
    }),
    [llmDescriptor.name]
  );

  const validationSchema = useMemo(
    () =>
      Yup.object().shape({
        [FIELD_API_BASE]: Yup.string().required("API Base URL is required"),
        [FIELD_DEFAULT_MODEL_NAME]: Yup.string().required(
          "Model name is required"
        ),
      }),
    []
  );

  const icon = () => (
    <ConnectionProviderIcon
      icon={<ProviderIcon provider={llmDescriptor.name} size={24} />}
    />
  );

  return (
    <OnboardingFormWrapper<LMStudioFormValues>
      icon={icon}
      title="Set up LM Studio"
      description="Connect to your LM Studio models."
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
      {(props) => <LMStudioFormFields {...props} />}
    </OnboardingFormWrapper>
  );
}
