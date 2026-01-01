import React, { useMemo, useState, useEffect } from "react";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import Separator from "@/refresh-components/Separator";
import IconButton from "@/refresh-components/buttons/IconButton";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/refresh-components/tabs/tabs";
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
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";

enum OllamaTab {
  SelfHosted = "self-hosted",
  Cloud = "cloud",
}

// Field name constants
const FIELD_API_BASE = "api_base";
const FIELD_DEFAULT_MODEL_NAME = "default_model_name";
const FIELD_OLLAMA_API_KEY = "custom_config.OLLAMA_API_KEY";

// URL constants
const OLLAMA_CLOUD_URL = "https://ollama.com";
const OLLAMA_SELF_HOSTED_DEFAULT_URL = "http://127.0.0.1:11434";

interface OllamaOnboardingFormProps {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface OllamaFormValues {
  name: string;
  provider: string;
  api_base: string;
  api_key_changed: boolean;
  default_model_name: string;
  model_configurations: any[];
  groups: number[];
  is_public: boolean;
  custom_config: {
    OLLAMA_API_KEY?: string;
  };
}

function OllamaFormFields({
  activeTab,
  setActiveTab,
  ...props
}: OnboardingFormChildProps<OllamaFormValues> & {
  activeTab: OllamaTab;
  setActiveTab: (tab: OllamaTab) => void;
}) {
  const {
    formikProps,
    apiStatus,
    showApiMessage,
    setShowApiMessage,
    errorMessage,
    setErrorMessage,
    setApiStatus,
    modelOptions,
    isFetchingModels,
    handleFetchModels,
    modelsApiStatus,
    modelsErrorMessage,
    showModelsApiErrorMessage,
    disabled,
  } = props;

  // Reset API status when tab changes
  useEffect(() => {
    setShowApiMessage(false);
    setErrorMessage("");
    setApiStatus("loading");
  }, [activeTab, setShowApiMessage, setErrorMessage, setApiStatus]);

  // Auto-fetch models for self-hosted Ollama on initial load
  useEffect(() => {
    if (activeTab === OllamaTab.SelfHosted && formikProps.values.api_base) {
      setApiStatus("loading");
      handleFetchModels();
    }
  }, []);

  // Set hidden fields based on active tab
  useEffect(() => {
    if (activeTab === OllamaTab.Cloud) {
      formikProps.setFieldValue(FIELD_API_BASE, OLLAMA_CLOUD_URL);
    } else {
      if (formikProps.values.api_base === OLLAMA_CLOUD_URL) {
        formikProps.setFieldValue(
          FIELD_API_BASE,
          OLLAMA_SELF_HOSTED_DEFAULT_URL
        );
      }

      // API key is not used for self-hosted Ollama
      formikProps.setFieldValue(FIELD_OLLAMA_API_KEY, "");
    }
  }, [activeTab]);

  return (
    <Tabs
      value={activeTab}
      onValueChange={(value) => setActiveTab(value as OllamaTab)}
      className="w-full"
    >
      <TabsList className="w-full">
        <TabsTrigger value={OllamaTab.SelfHosted} className="flex-1">
          Self-hosted Ollama
        </TabsTrigger>
        <TabsTrigger value={OllamaTab.Cloud} className="flex-1">
          Ollama Cloud
        </TabsTrigger>
      </TabsList>

      <TabsContent value={OllamaTab.SelfHosted} className="w-full">
        <div className="flex flex-col gap-4 w-full">
          <FormikField<string>
            name={FIELD_API_BASE}
            render={(field, helper, meta, state) => (
              <FormField name={FIELD_API_BASE} state={state} className="w-full">
                <FormField.Label>API Base URL</FormField.Label>
                <FormField.Control>
                  <InputTypeIn
                    {...field}
                    placeholder={OLLAMA_SELF_HOSTED_DEFAULT_URL}
                    error={apiStatus === "error"}
                    showClearButton={false}
                    disabled={disabled}
                  />
                </FormField.Control>
                {showApiMessage && (
                  <FormField.APIMessage
                    state={apiStatus}
                    messages={{
                      loading: "Checking connection to Ollama...",
                      success: "Connected successfully.",
                      error: errorMessage || "Failed to connect",
                    }}
                  />
                )}
                {!showApiMessage && (
                  <FormField.Message
                    messages={{
                      idle: "Your self-hosted Ollama API base URL.",
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
      </TabsContent>

      <TabsContent value={OllamaTab.Cloud} className="w-full">
        <div className="flex flex-col gap-4 w-full">
          <FormikField<string>
            name={FIELD_OLLAMA_API_KEY}
            render={(field, helper, meta, state) => (
              <FormField
                name={FIELD_OLLAMA_API_KEY}
                state={state}
                className="w-full"
              >
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
                      if (field.value) {
                        handleFetchModels();
                      }
                    }}
                  />
                </FormField.Control>
                {showApiMessage && (
                  <FormField.APIMessage
                    state={apiStatus}
                    messages={{
                      loading: "Checking API key with Ollama Cloud...",
                      success: "API key valid. Your available models updated.",
                      error: errorMessage || "Invalid API key",
                    }}
                  />
                )}
                {!showApiMessage && (
                  <FormField.Message
                    messages={{
                      idle: (
                        <>
                          {"Paste your "}
                          <InlineExternalLink href="https://ollama.com">
                            API key
                          </InlineExternalLink>
                          {" from Ollama Cloud to access your models."}
                        </>
                      ),
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
      </TabsContent>
    </Tabs>
  );
}

export function OllamaOnboardingForm({
  llmDescriptor,
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
}: OllamaOnboardingFormProps) {
  const [activeTab, setActiveTab] = useState<OllamaTab>(OllamaTab.SelfHosted);

  const initialValues = useMemo(
    (): OllamaFormValues => ({
      ...buildInitialValues(),
      name: llmDescriptor.name,
      provider: llmDescriptor.name,
      api_base: OLLAMA_SELF_HOSTED_DEFAULT_URL,
      custom_config: {
        OLLAMA_API_KEY: "",
      },
    }),
    [llmDescriptor.name]
  );

  // Dynamic validation based on active tab
  const validationSchema = useMemo(() => {
    if (activeTab === OllamaTab.SelfHosted) {
      return Yup.object().shape({
        [FIELD_API_BASE]: Yup.string().required("API Base is required"),
        [FIELD_DEFAULT_MODEL_NAME]: Yup.string().required(
          "Model name is required"
        ),
      });
    } else {
      return Yup.object().shape({
        custom_config: Yup.object().shape({
          OLLAMA_API_KEY: Yup.string().required("API Key is required"),
        }),
        [FIELD_DEFAULT_MODEL_NAME]: Yup.string().required(
          "Model name is required"
        ),
      });
    }
  }, [activeTab]);

  const icon = () => (
    <ConnectionProviderIcon
      icon={<ProviderIcon provider={llmDescriptor.name} size={24} />}
    />
  );

  return (
    <OnboardingFormWrapper<OllamaFormValues>
      icon={icon}
      title="Set up Ollama"
      description="Connect to your Ollama models."
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
      {(props) => (
        <OllamaFormFields
          {...props}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
        />
      )}
    </OnboardingFormWrapper>
  );
}
