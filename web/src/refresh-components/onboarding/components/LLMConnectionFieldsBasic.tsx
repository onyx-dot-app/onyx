import React from "react";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { Separator } from "@/components/ui/separator";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import InputFile from "@/refresh-components/inputs/InputFile";
import {
  PROVIDER_SKIP_FIELDS,
  BEDROCK_AUTH_FIELDS,
  HIDE_API_MESSAGE_FIELDS,
} from "../constants";
import SvgRefreshCw from "@/icons/refresh-cw";
import IconButton from "@/refresh-components/buttons/IconButton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Info } from "lucide-react";
import Text from "@/refresh-components/texts/Text";

type Props = {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  modalContent?: any;
  modelOptions: Array<{ label: string; value: string }>;
  showApiMessage: boolean;
  apiStatus: "idle" | "loading" | "success" | "error";
  errorMessage: string;
  isFetchingModels: boolean;
  onApiKeyBlur: (apiKey: string) => void;
  formikValues: any;
  setDefaultModelName: (value: string) => void;
  onFetchModels?: () => void;
  canFetchModels?: boolean;
  modelsApiStatus: "idle" | "loading" | "success" | "error";
  modelsErrorMessage: string;
  showModelsApiErrorMessage: boolean;
  testModelChangeWithApiKey: (modelName: string) => Promise<void>;
  testFileInputChange: (
    customConfig: Record<string, any>
  ) => Promise<void> | void;
  disabled?: boolean;
};

export const LLMConnectionFieldsBasic: React.FC<Props> = ({
  llmDescriptor,
  modalContent,
  modelOptions,
  showApiMessage,
  apiStatus,
  errorMessage,
  isFetchingModels,
  onApiKeyBlur,
  formikValues,
  setDefaultModelName,
  onFetchModels,
  canFetchModels,
  modelsApiStatus,
  modelsErrorMessage,
  showModelsApiErrorMessage,
  testModelChangeWithApiKey,
  testFileInputChange,
  disabled = false,
}) => {
  const handleApiKeyInteraction = (apiKey: string) => {
    if (!apiKey) return;
    if (llmDescriptor?.name === "openrouter") {
      onFetchModels?.();
    } else {
      onApiKeyBlur(apiKey);
    }
  };
  return (
    <>
      {llmDescriptor?.name === "azure" ? (
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
                      Paste your endpoint target URI from
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
      ) : (
        <>
          {llmDescriptor?.api_base_required && (
            <FormikField<string>
              name="api_base"
              render={(field, helper, meta, state) => (
                <FormField name="api_base" state={state} className="w-full">
                  <FormField.Label>API Base</FormField.Label>
                  <FormField.Control>
                    <InputTypeIn
                      {...field}
                      placeholder="API Base"
                      showClearButton={false}
                      disabled={disabled}
                    />
                  </FormField.Control>
                </FormField>
              )}
            />
          )}
          {llmDescriptor?.api_version_required && (
            <FormikField<string>
              name="api_version"
              render={(field, helper, meta, state) => (
                <FormField name="api_version" state={state} className="w-full">
                  <FormField.Label>API Version</FormField.Label>
                  <FormField.Control>
                    <InputTypeIn
                      {...field}
                      placeholder="API Version"
                      showClearButton={false}
                      disabled={disabled}
                    />
                  </FormField.Control>
                </FormField>
              )}
            />
          )}
        </>
      )}

      {llmDescriptor?.api_key_required && (
        <FormikField<string>
          name="api_key"
          render={(field, helper, meta, state) => (
            <FormField name="api_key" state={state} className="w-full">
              <FormField.Label>API Key</FormField.Label>
              <FormField.Control>
                <PasswordInputTypeIn
                  {...field}
                  placeholder=""
                  onBlur={(e) => {
                    field.onBlur(e);
                    handleApiKeyInteraction(field.value);
                  }}
                  showClearButton={false}
                  disabled={
                    disabled ||
                    (llmDescriptor?.name === "azure" &&
                      !formikValues.target_uri?.trim())
                  }
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
                    loading: `Checking API key with ${modalContent?.display_name}...`,
                    success: "API key valid. Your available models updated.",
                    error: errorMessage || "Invalid API key",
                  }}
                />
              )}
            </FormField>
          )}
        />
      )}

      {llmDescriptor?.custom_config_keys?.map((customConfigKey) => {
        const isSkipped = PROVIDER_SKIP_FIELDS[llmDescriptor?.name]?.includes(
          customConfigKey.name
        );
        if (isSkipped) return null;

        // Frontend-only filtering for Bedrock based on chosen auth method
        if (llmDescriptor?.name === "bedrock") {
          const selectedAuth =
            formikValues?.custom_config?.BEDROCK_AUTH_METHOD || "access_key";
          const allowed =
            BEDROCK_AUTH_FIELDS[
              selectedAuth as keyof typeof BEDROCK_AUTH_FIELDS
            ];
          if (!allowed?.includes(customConfigKey.name)) {
            return null;
          }
        }

        return (
          <>
            <FormikField<string>
              key={customConfigKey.name}
              name={`custom_config.${customConfigKey.name}`}
              render={(field, helper, meta, state) => (
                <FormField
                  name={`custom_config.${customConfigKey.name}`}
                  state={state}
                  className="w-full"
                >
                  <FormField.Label>
                    {customConfigKey.display_name || customConfigKey.name}
                  </FormField.Label>
                  <FormField.Control>
                    {customConfigKey.key_type === "select" ? (
                      <InputSelect
                        value={
                          (field.value as string) ??
                          (customConfigKey.default_value as string) ??
                          ""
                        }
                        onValueChange={(value) => helper.setValue(value)}
                        options={
                          customConfigKey.options?.map((opt) => ({
                            label: opt.label,
                            value: opt.value,
                            description: opt?.description ?? undefined,
                          })) ?? []
                        }
                        disabled={disabled}
                      />
                    ) : customConfigKey.key_type === "file_input" ? (
                      <InputFile
                        placeholder={customConfigKey.default_value || ""}
                        setValue={(value) => helper.setValue(value)}
                        onValueSet={(value) =>
                          testFileInputChange({ [customConfigKey.name]: value })
                        }
                        onBlur={(e) => {
                          field.onBlur(e);
                          if (field.value) {
                            testFileInputChange({
                              [customConfigKey.name]: field.value,
                            });
                          }
                        }}
                        showClearButton={true}
                        disabled={disabled}
                      />
                    ) : customConfigKey.is_secret ? (
                      <PasswordInputTypeIn
                        {...field}
                        placeholder={customConfigKey.default_value || ""}
                        showClearButton={false}
                        disabled={disabled}
                      />
                    ) : (
                      <InputTypeIn
                        {...field}
                        placeholder={customConfigKey.default_value || ""}
                        showClearButton={false}
                        disabled={disabled}
                      />
                    )}
                  </FormField.Control>
                  {(() => {
                    const alwaysShowDesc = HIDE_API_MESSAGE_FIELDS[
                      llmDescriptor?.name as string
                    ]?.includes(customConfigKey.name);
                    const hasDesc = !!customConfigKey.description;
                    return (
                      hasDesc &&
                      (alwaysShowDesc || (!alwaysShowDesc && !showApiMessage))
                    );
                  })() && (
                    <FormField.Message
                      messages={{
                        idle: (
                          <>
                            {modalContent?.field_metadata?.[
                              customConfigKey.name
                            ] ?? customConfigKey.description}
                          </>
                        ),
                        error: meta.error,
                      }}
                    />
                  )}
                  {llmDescriptor?.name === "bedrock" &&
                    customConfigKey.name === "BEDROCK_AUTH_METHOD" &&
                    ((field.value as string) ??
                      (customConfigKey.default_value as string) ??
                      "") === "iam" && (
                      <div className="flex gap-1 p-2 border border-border-01 rounded-12 bg-background-tint-01">
                        <div className="p-1">
                          <Info className="h-4 w-4 stroke-text-03" />
                        </div>
                        <Text text04 mainUiBody>
                          Onyx will use the IAM role attached to the environment
                          it&apos;s running in to authenticate.
                        </Text>
                      </div>
                    )}
                  {showApiMessage &&
                    !HIDE_API_MESSAGE_FIELDS[llmDescriptor?.name]?.includes(
                      customConfigKey.name
                    ) && (
                      <FormField.APIMessage
                        state={apiStatus}
                        messages={{
                          loading: `Checking API key with ${modalContent?.display_name}...`,
                          success:
                            "API key valid. Your available models updated.",
                          error: errorMessage || "Invalid API key",
                        }}
                      />
                    )}
                </FormField>
              )}
            />
          </>
        );
      })}

      <Separator className="my-0" />

      <FormikField<string>
        name="default_model_name"
        render={(field, helper, meta, state) => (
          <FormField name="default_model_name" state={state} className="w-full">
            <FormField.Label>Default Model</FormField.Label>
            <FormField.Control>
              {modelOptions.length > 0 && (
                <InputSelect
                  value={field.value}
                  onValueChange={(value) => {
                    helper.setValue(value);
                    setDefaultModelName(value);
                    if (testModelChangeWithApiKey && value) {
                      testModelChangeWithApiKey(value);
                    }
                  }}
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
              )}
              {modelOptions.length === 0 && (
                <InputTypeIn
                  value={field.value}
                  onChange={(e) => {
                    helper.setValue(e.target.value);
                    setDefaultModelName(e.target.value);
                  }}
                  placeholder="E.g. gpt-4"
                  showClearButton={false}
                  disabled={disabled}
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
};
