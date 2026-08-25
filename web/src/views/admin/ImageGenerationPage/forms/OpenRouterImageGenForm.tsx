"use client";

import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import { InputTypeIn } from "@opal/components";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { ImageGenFormWrapper } from "@/views/admin/ImageGenerationPage/forms/ImageGenFormWrapper";
import {
  ImageGenFormBaseProps,
  ImageGenFormChildProps,
  ImageGenSubmitPayload,
} from "@/views/admin/ImageGenerationPage/forms/types";
import { ImageGenerationCredentials } from "@/views/admin/ImageGenerationPage/svc";
import { ImageProvider } from "@/views/admin/ImageGenerationPage/constants";

const OPENROUTER_PROVIDER_NAME = "openrouter";
const DEFAULT_OPENROUTER_MODEL = "bytedance-seed/seedream-4.5";

interface OpenRouterFormValues {
  model_name: string;
  api_key: string;
}

const initialValues: OpenRouterFormValues = {
  model_name: DEFAULT_OPENROUTER_MODEL,
  api_key: "",
};

const validationSchema = Yup.object().shape({
  model_name: Yup.string().required("Model slug is required"),
  api_key: Yup.string().required("API Key is required"),
});

function getInitialValuesFromCredentials(
  credentials: ImageGenerationCredentials,
  _imageProvider: ImageProvider
): Partial<OpenRouterFormValues> {
  return {
    api_key: credentials.api_key || "",
  };
}

function transformValues(
  values: OpenRouterFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  return {
    modelName: values.model_name.trim(),
    imageProviderId: imageProvider.image_provider_id,
    provider: OPENROUTER_PROVIDER_NAME,
    apiKey: values.api_key,
  };
}

function OpenRouterFormFields(
  props: ImageGenFormChildProps<OpenRouterFormValues>
) {
  const {
    apiStatus,
    showApiMessage,
    errorMessage,
    disabled,
    isLoadingCredentials,
    apiKeyOptions,
    resetApiState,
    imageProvider,
  } = props;

  return (
    <>
      <FormikField<string>
        name="model_name"
        render={(field, helper, meta, state) => (
          <FormField name="model_name" state={state} className="w-full">
            <FormField.Label>Model Slug</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                value={field.value}
                onChange={(e) => {
                  helper.setValue(e.target.value);
                  resetApiState();
                }}
                onBlur={field.onBlur}
                placeholder="bytedance-seed/seedream-4.5"
                variant={disabled ? "disabled" : undefined}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: "Enter any OpenRouter image model slug from the image models page.",
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />
      <FormikField<string>
        name="api_key"
        render={(field, helper, meta, state) => (
          <FormField
            name="api_key"
            state={apiStatus === "error" ? "error" : state}
            className="w-full"
          >
            <FormField.Label>API Key</FormField.Label>
            <FormField.Control>
              {apiKeyOptions.length > 0 ? (
                <InputComboBox
                  value={field.value}
                  onChange={(e) => {
                    helper.setValue(e.target.value);
                    resetApiState();
                  }}
                  onValueChange={(value) => {
                    helper.setValue(value);
                    resetApiState();
                  }}
                  onBlur={field.onBlur}
                  options={apiKeyOptions}
                  placeholder={
                    isLoadingCredentials
                      ? "Loading..."
                      : "Enter new API key or select existing provider"
                  }
                  disabled={disabled}
                  isError={apiStatus === "error"}
                />
              ) : (
                <PasswordInputTypeIn
                  {...field}
                  onChange={(e) => {
                    field.onChange(e);
                    resetApiState();
                  }}
                  placeholder={
                    isLoadingCredentials ? "Loading..." : "Enter your API key"
                  }
                  disabled={disabled}
                  error={apiStatus === "error"}
                />
              )}
            </FormField.Control>
            {showApiMessage ? (
              <FormField.APIMessage
                state={apiStatus}
                messages={{
                  loading: `Testing API key with ${imageProvider.title}...`,
                  success: "API key is valid. Configuration saved.",
                  error: errorMessage || "Invalid API key",
                }}
              />
            ) : (
              <FormField.Message
                messages={{
                  idle: "Enter a new API key or select an existing OpenRouter provider.",
                  error: meta.error,
                }}
              />
            )}
          </FormField>
        )}
      />
    </>
  );
}

export function OpenRouterImageGenForm(props: ImageGenFormBaseProps) {
  const { imageProvider, existingConfig } = props;
  const modelName =
    existingConfig?.model_name || imageProvider.model_name || DEFAULT_OPENROUTER_MODEL;

  return (
    <ImageGenFormWrapper<OpenRouterFormValues>
      {...props}
      title={
        existingConfig
          ? `Edit ${imageProvider.title}`
          : `Connect ${imageProvider.title}`
      }
      description={imageProvider.description}
      initialValues={{
        ...initialValues,
        model_name: modelName,
      }}
      validationSchema={validationSchema}
      getInitialValuesFromCredentials={getInitialValuesFromCredentials}
      transformValues={(values) => transformValues(values, imageProvider)}
    >
      {(childProps) => <OpenRouterFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
