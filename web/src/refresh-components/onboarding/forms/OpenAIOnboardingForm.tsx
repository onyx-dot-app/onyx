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
import { MODAL_CONTENT_MAP } from "../constants";
import LLMConnectionIcons from "../components/LLMConnectionIcons";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";

interface OpenAIOnboardingFormProps {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface OpenAIFormValues {
  name: string;
  provider: string;
  api_key: string;
  api_key_changed: boolean;
  default_model_name: string;
  model_configurations: any[];
  groups: number[];
  is_public: boolean;
}

function OpenAIFormFields({
  formikProps,
}: {
  formikProps: FormikProps<OpenAIFormValues>;
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

  const modalContent = MODAL_CONTENT_MAP[llmDescriptor?.name ?? ""];

  return (
    <>
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
                disabled={disabled}
              />
            </FormField.Control>
            {!showApiMessage && (
              <FormField.Message
                messages={{
                  idle:
                    modalContent?.field_metadata?.api_key ??
                    "Paste your API key to access your models.",
                  error: meta.error,
                }}
              />
            )}
            {showApiMessage && (
              <FormField.APIMessage
                state={apiStatus}
                messages={{
                  loading: `Checking API key with ${
                    modalContent?.display_name ?? "OpenAI"
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
                  idle: modalContent?.field_metadata?.default_model_name,
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

export function OpenAIOnboardingForm({
  llmDescriptor,
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
}: OpenAIOnboardingFormProps) {
  const initialValues = useMemo(
    () => buildInitialValues(llmDescriptor, false) as OpenAIFormValues,
    [llmDescriptor]
  );

  const validationSchema = Yup.object().shape({
    api_key: Yup.string().required("API Key is required"),
    default_model_name: Yup.string().required("Model name is required"),
  });

  const icon = () => (
    <LLMConnectionIcons
      icon={<ProviderIcon provider={llmDescriptor.name} size={24} />}
    />
  );

  return (
    <OnboardingFormWrapper<OpenAIFormValues>
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
    >
      {(formikProps) => <OpenAIFormFields formikProps={formikProps} />}
    </OnboardingFormWrapper>
  );
}
