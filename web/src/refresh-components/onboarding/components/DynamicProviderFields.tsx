import React from "react";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { MODAL_CONTENT_MAP } from "../constants";
import { APIFormFieldState } from "@/refresh-components/form/types";
import SvgRefreshCw from "@/icons/refresh-cw";
import IconButton from "@/refresh-components/buttons/IconButton";

interface DynamicProviderFieldsProps {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  fields: string[];
  modelOptions: Array<{ label: string; value: string }>;
  fieldOverrides?: Record<
    string,
    {
      placeholder?: string;
      description?: string;
    }
  >;
  onApiKeyBlur?: (apiKey: string) => void;
  showApiMessage?: boolean;
  apiStatus?: APIFormFieldState;
  errorMessage?: string;
  onFetchModels?: () => void;
  isFetchingModels?: boolean;
  canFetchModels?: boolean;
  testModelChangeWithApiKey?: (modelName: string) => Promise<void>;
  modelsApiStatus?: APIFormFieldState;
  modelsErrorMessage?: string;
  showModelsApiErrorMessage?: boolean;
  disabled?: boolean;
}

export const DynamicProviderFields: React.FC<DynamicProviderFieldsProps> = ({
  llmDescriptor,
  fields,
  modelOptions,
  fieldOverrides = {},
  onApiKeyBlur,
  showApiMessage = false,
  apiStatus = "loading",
  errorMessage = "",
  onFetchModels,
  isFetchingModels = false,
  canFetchModels = false,
  testModelChangeWithApiKey,
  modelsApiStatus = "loading",
  modelsErrorMessage = "",
  showModelsApiErrorMessage = false,
  disabled = false,
}) => {
  const modalContent = MODAL_CONTENT_MAP[llmDescriptor.name];
  const handleApiKeyInteraction = (apiKey: string) => {
    if (!apiKey) return;
    if (llmDescriptor?.name === "ollama_chat") {
      onFetchModels?.();
    } else {
      onApiKeyBlur?.(apiKey);
    }
  };

  const renderField = (fieldPath: string) => {
    const override = fieldOverrides[fieldPath];

    // Handle API Base field
    if (fieldPath === "api_base" && llmDescriptor.api_base_required) {
      return (
        <FormikField<string>
          key={fieldPath}
          name="api_base"
          render={(field, helper, meta, state) => (
            <FormField name="api_base" state={state} className="w-full">
              <FormField.Label>API Base URL</FormField.Label>
              <FormField.Control>
                <InputTypeIn
                  {...field}
                  isError={apiStatus === "error"}
                  placeholder={
                    override?.placeholder ||
                    llmDescriptor.default_api_base ||
                    "API Base URL"
                  }
                  disabled={disabled}
                  showClearButton={false}
                />
              </FormField.Control>
              {showApiMessage && (
                <FormField.APIMessage
                  state={apiStatus}
                  messages={{
                    loading: `Checking with your API base URL...`,
                    success:
                      "API base URL valid. Your available models updated.",
                    error: errorMessage || "Invalid API base URL",
                  }}
                />
              )}
              {!showApiMessage && (
                <FormField.Message
                  messages={{
                    idle:
                      override?.description ||
                      modalContent?.field_metadata?.api_base ||
                      "The base URL for your API endpoint.",
                    error: meta.error,
                  }}
                />
              )}
            </FormField>
          )}
        />
      );
    }

    // Handle Custom Config fields (nested fields like custom_config.OLLAMA_API_KEY)
    if (fieldPath.startsWith("custom_config.")) {
      const configKey = fieldPath.split(".")[1];
      const customConfigKey = llmDescriptor.custom_config_keys?.find(
        (k) => k.name === configKey
      );

      if (!customConfigKey) return null;
      const isApiKey = fieldPath.includes("API_KEY");

      return (
        <FormikField<string>
          key={fieldPath}
          name={fieldPath}
          render={(field, helper, meta, state) => (
            <FormField name={fieldPath} state={state} className="w-full">
              <FormField.Label>
                {customConfigKey.display_name || customConfigKey.name}
              </FormField.Label>
              <FormField.Control>
                {customConfigKey.is_secret ? (
                  <PasswordInputTypeIn
                    {...field}
                    placeholder={override?.placeholder || ""}
                    disabled={disabled}
                    showClearButton={false}
                    onBlur={(e) => {
                      field.onBlur(e);
                      handleApiKeyInteraction(field.value);
                    }}
                    isError={apiStatus === "error"}
                  />
                ) : (
                  <InputTypeIn
                    {...field}
                    placeholder={override?.placeholder || ""}
                    disabled={disabled}
                    showClearButton={false}
                    isError={apiStatus === "error"}
                    onBlur={(e) => {
                      field.onBlur(e);
                      handleApiKeyInteraction(field.value);
                    }}
                  />
                )}
              </FormField.Control>
              {showApiMessage && (
                <FormField.APIMessage
                  state={apiStatus}
                  messages={{
                    loading: `Checking ${
                      isApiKey ? "API key" : "API base URL"
                    }...`,
                    success: `${
                      isApiKey ? "API key" : "API base URL"
                    } valid. Your available models updated.`,
                    error:
                      errorMessage ||
                      `Invalid ${isApiKey ? "API key" : "API base URL"}`,
                  }}
                />
              )}
              {!showApiMessage && (
                <FormField.Message
                  messages={{
                    idle:
                      override?.description ||
                      modalContent?.field_metadata?.[customConfigKey.name] ||
                      "",
                    error: meta.error,
                  }}
                />
              )}
            </FormField>
          )}
        />
      );
    }

    // Handle Default Model field
    if (fieldPath === "default_model_name") {
      return (
        <FormikField<string>
          key={fieldPath}
          name="default_model_name"
          render={(field, helper, meta, state) => (
            <FormField
              name="default_model_name"
              state={state}
              className="w-full"
            >
              <FormField.Label>Default Model</FormField.Label>
              <FormField.Control>
                {modelOptions.length > 0 ? (
                  <InputSelect
                    value={field.value}
                    onValueChange={(value) => {
                      helper.setValue(value);
                      if (testModelChangeWithApiKey && value) {
                        testModelChangeWithApiKey(value);
                      }
                    }}
                    error={modelsApiStatus === "error"}
                    options={modelOptions}
                    disabled={
                      disabled || modelOptions.length === 0 || isFetchingModels
                    }
                    rightSection={
                      canFetchModels ? (
                        <IconButton
                          internal
                          icon={SvgRefreshCw}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            onFetchModels?.();
                          }}
                          tooltip="Fetch available models"
                          disabled={disabled || isFetchingModels}
                          className={isFetchingModels ? "animate-spin" : ""}
                        />
                      ) : undefined
                    }
                  />
                ) : (
                  <InputTypeIn
                    value={field.value}
                    onChange={(e) => {
                      helper.setValue(e.target.value);
                    }}
                    isError={modelsApiStatus === "error"}
                    placeholder="E.g. gpt-4"
                    disabled={disabled}
                    showClearButton={false}
                    rightSection={
                      canFetchModels ? (
                        <IconButton
                          internal
                          icon={SvgRefreshCw}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            onFetchModels?.();
                          }}
                          tooltip="Fetch available models"
                          disabled={disabled || isFetchingModels}
                          className={isFetchingModels ? "animate-spin" : ""}
                        />
                      ) : undefined
                    }
                  />
                )}
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
                    idle:
                      override?.description ||
                      modalContent?.field_metadata?.default_model_name ||
                      "This model will be used by Onyx by default.",
                    error: meta.error,
                  }}
                />
              )}
            </FormField>
          )}
        />
      );
    }

    return null;
  };

  return <>{fields.map(renderField)}</>;
};
