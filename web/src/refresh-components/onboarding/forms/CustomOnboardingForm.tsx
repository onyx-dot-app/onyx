import { useMemo, useState } from "react";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import Separator from "@/refresh-components/Separator";
import Text from "@/refresh-components/texts/Text";
import KeyValueInput, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import { SvgServer } from "@opal/icons";
import {
  OnboardingFormWrapper,
  OnboardingFormChildProps,
} from "./OnboardingFormWrapper";
import { OnboardingActions, OnboardingState } from "../types";
import { buildInitialValues } from "../components/llmConnectionHelpers";
import ConnectionProviderIcon from "@/refresh-components/ConnectionProviderIcon";

// Field name constants
const FIELD_PROVIDER = "provider";
const FIELD_API_BASE = "api_base";
const FIELD_API_VERSION = "api_version";
const FIELD_API_KEY = "api_key";
const FIELD_CUSTOM_CONFIG = "custom_config";
const FIELD_MODEL_CONFIGURATIONS = "model_configurations";
const FIELD_DEFAULT_MODEL_NAME = "default_model_name";

interface CustomOnboardingFormProps {
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface CustomFormValues {
  name: string;
  provider: string;
  api_key: string;
  api_base: string;
  api_version: string;
  api_key_changed: boolean;
  default_model_name: string;
  model_configurations: any[];
  custom_config: Record<string, string>;
  groups: number[];
  is_public: boolean;
  deployment_name: string;
  target_uri: string;
}

function CustomFormFields(props: OnboardingFormChildProps<CustomFormValues>) {
  const { formikProps, apiStatus, showApiMessage, errorMessage, disabled } =
    props;

  const [modelConfigError, setModelConfigError] = useState<string | null>(null);
  const [customConfigDraft, setCustomConfigDraft] = useState<KeyValue[]>(
    Object.entries(formikProps.values.custom_config || {}).map(
      ([key, value]) => ({ key, value: String(value) })
    )
  );

  const handleModelConfigsChange = (items: KeyValue[]) => {
    const configs = items.map((item) => ({
      name: item.key,
      is_visible: true,
      max_input_tokens: (() => {
        const t = item.value.trim();
        if (t === "") return null;
        if (!/^\d+$/.test(t)) return item.value;
        return parseInt(t, 10);
      })(),
      supports_image_input: false,
    }));

    formikProps.setFieldValue("model_configurations", configs);
  };

  const handleCustomConfigsChange = (items: KeyValue[]) => {
    // Preserve UI rows (including temporary duplicate/empty keys)
    setCustomConfigDraft(items);

    // Convert KeyValue[] to Record<string, string> for form value
    const config: Record<string, string> = {};
    items.forEach((item) => {
      config[item.key] = item.value;
    });
    formikProps.setFieldValue("custom_config", config);
  };

  // Convert model_configurations back to KeyValue[] for display
  const modelConfigsAsKeyValue: KeyValue[] =
    formikProps.values.model_configurations?.map((config: any) => ({
      key: config.name || "",
      value: config.max_input_tokens?.toString() || "",
    })) || [];

  return (
    <div className="flex flex-col gap-2 w-full">
      <FormikField<string>
        name={FIELD_PROVIDER}
        render={(field, helper, meta, state) => (
          <FormField name={FIELD_PROVIDER} state={state} className="w-full">
            <FormField.Label>Provider Name</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                placeholder="E.g. openai, anthropic, etc."
                showClearButton={false}
                disabled={disabled}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: (
                  <>
                    See full list of supported LLM providers at{" "}
                    <a
                      href="https://docs.litellm.ai/docs/providers"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline"
                    >
                      LiteLLM
                    </a>
                    .
                  </>
                ),
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />

      <Separator />

      <Text as="p" text03 secondaryBody className="ml-0.5">
        Fill in the following fields as needed. Refer to{" "}
        <a
          href="https://docs.litellm.ai/docs/"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          LiteLLM documentation
        </a>{" "}
        for instructions of the model provider you are using.
      </Text>

      <FormikField<string>
        name={FIELD_API_BASE}
        render={(field, helper, meta, state) => (
          <FormField name={FIELD_API_BASE} state={state} className="w-full">
            <FormField.Label optional>API Base URL</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                placeholder="https://"
                showClearButton={false}
                disabled={disabled}
                error={
                  typeof field.value === "string" &&
                  field.value.trim() !== "" &&
                  apiStatus === "error"
                }
              />
            </FormField.Control>
            {showApiMessage &&
              typeof field.value === "string" &&
              field.value.trim() !== "" && (
                <FormField.APIMessage
                  state={apiStatus}
                  messages={{
                    loading: "Checking API configuration...",
                    success: "API key valid. Your available models updated.",
                    error: errorMessage || "Invalid API key",
                  }}
                />
              )}
          </FormField>
        )}
      />

      <FormikField<string>
        name={FIELD_API_VERSION}
        render={(field, helper, meta, state) => (
          <FormField name={FIELD_API_VERSION} state={state} className="w-full">
            <FormField.Label optional>API Version</FormField.Label>
            <FormField.Control>
              <InputTypeIn {...field} placeholder="" showClearButton={false} />
            </FormField.Control>
          </FormField>
        )}
      />

      <FormikField<string>
        name={FIELD_API_KEY}
        render={(field, helper, meta, state) => (
          <FormField name={FIELD_API_KEY} state={state} className="w-full">
            <FormField.Label optional>API Key</FormField.Label>
            <FormField.Control>
              <PasswordInputTypeIn
                {...field}
                placeholder=""
                showClearButton={false}
                disabled={disabled}
                error={apiStatus === "error"}
              />
            </FormField.Control>
            {showApiMessage && (
              <FormField.APIMessage
                state={apiStatus}
                messages={{
                  loading: "Checking API key...",
                  success: "API key valid. Your available models updated.",
                  error: errorMessage || "Invalid API key",
                }}
              />
            )}
          </FormField>
        )}
      />

      <Separator />

      <div className="w-full">
        <FormField
          name={FIELD_CUSTOM_CONFIG}
          state={formikProps.errors.custom_config ? "error" : "idle"}
          className="w-full"
        >
          <FormField.Label optional>Additional Configs</FormField.Label>
          <FormField.Description>
            Optional additional properties as needed by the model provider. This
            is passed to LiteLLM{" "}
            <span className="font-secondary-mono text-text-03 whitespace-nowrap inline-block">
              completion()
            </span>{" "}
            call as arguments in the environment variable.
          </FormField.Description>
          <FormField.Control asChild>
            <KeyValueInput
              keyTitle="Key"
              valueTitle="Value"
              items={customConfigDraft}
              onChange={handleCustomConfigsChange}
              mode="line"
              disabled={disabled}
            />
          </FormField.Control>
        </FormField>
      </div>

      <Separator />

      <div className="w-full">
        <FormField
          name={FIELD_MODEL_CONFIGURATIONS}
          state={
            formikProps.errors.model_configurations || modelConfigError
              ? "error"
              : "idle"
          }
          className="w-full"
        >
          <FormField.Label>Model Configs</FormField.Label>
          <FormField.Description>
            List LLM models you wish to use and their configurations for this
            provider.
          </FormField.Description>
          <FormField.Control asChild>
            <KeyValueInput
              keyTitle="Model Name"
              valueTitle="Max Input Tokens"
              items={modelConfigsAsKeyValue}
              onChange={handleModelConfigsChange}
              onValueValidate={(value) => {
                const v = (value || "").trim();
                if (v === "") return { isValid: true };
                return /^\d+$/.test(v)
                  ? { isValid: true }
                  : { isValid: false, message: "Must be a number" };
              }}
              onValidationError={setModelConfigError}
              mode="fixed-line"
              disabled={disabled}
            />
          </FormField.Control>
        </FormField>
      </div>

      <Separator />

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
              <InputTypeIn
                {...field}
                placeholder="model-name"
                showClearButton={false}
                disabled={disabled}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: "This model will be used by Onyx by default for this provider. This must be one of the models listed above.",
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />
    </div>
  );
}

export function CustomOnboardingForm({
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
}: CustomOnboardingFormProps) {
  const initialValues = useMemo(
    (): CustomFormValues => ({
      ...buildInitialValues(),
      model_configurations: [
        {
          name: "",
          is_visible: true,
          max_input_tokens: null,
          supports_image_input: false,
        },
      ],
    }),
    []
  );

  const validationSchema = Yup.object().shape({
    [FIELD_PROVIDER]: Yup.string().required("Provider is required"),
    [FIELD_API_KEY]: Yup.string(),
    [FIELD_API_BASE]: Yup.string(),
    [FIELD_API_VERSION]: Yup.string(),
    [FIELD_MODEL_CONFIGURATIONS]: Yup.array()
      .of(
        Yup.object({
          name: Yup.string().required("Model name is required"),
          is_visible: Yup.boolean().required("Visibility is required"),
          max_input_tokens: Yup.number()
            .transform((value, originalValue) =>
              originalValue === "" ||
              originalValue === undefined ||
              originalValue === null
                ? null
                : value
            )
            .nullable()
            .optional(),
        })
      )
      .min(1, "At least one model configuration is required"),
    [FIELD_DEFAULT_MODEL_NAME]: Yup.string().required(
      "Default model is required"
    ),
    [FIELD_CUSTOM_CONFIG]: Yup.object(),
  });

  const icon = () => (
    <ConnectionProviderIcon
      icon={<SvgServer className="w-6 h-6 stroke-text-04" />}
    />
  );

  return (
    <OnboardingFormWrapper<CustomFormValues>
      icon={icon}
      title="Set up Custom LLM Provider"
      description="Connect models from other providers or your self-hosted models."
      isCustomProvider={true}
      onboardingState={onboardingState}
      onboardingActions={onboardingActions}
      open={open}
      onOpenChange={onOpenChange}
      initialValues={initialValues}
      validationSchema={validationSchema}
      transformValues={(values, fetchedModels) => {
        // For custom providers, use the values from the form and filter out empty entries
        const modelConfigsToUse = (values.model_configurations || []).filter(
          (config: any) => config.name && config.name.trim() !== ""
        );

        // Filter out empty custom config entries
        const filteredCustomConfig: Record<string, string> = {};
        Object.entries(values.custom_config || {}).forEach(([key, value]) => {
          if (key.trim() !== "") {
            filteredCustomConfig[key] = value;
          }
        });

        return {
          ...values,
          model_configurations: modelConfigsToUse,
          custom_config:
            Object.keys(filteredCustomConfig).length > 0
              ? filteredCustomConfig
              : undefined,
        };
      }}
    >
      {(props) => <CustomFormFields {...props} />}
    </OnboardingFormWrapper>
  );
}
