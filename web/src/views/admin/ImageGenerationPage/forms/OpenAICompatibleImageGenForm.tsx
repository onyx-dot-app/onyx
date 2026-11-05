"use client";

import React from "react";
import { InputTypeIn, PasswordInputTypeIn } from "@opal/components";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import { ImageGenFormWrapper } from "@/views/admin/ImageGenerationPage/forms/ImageGenFormWrapper";
import {
  ImageGenFormBaseProps,
  ImageGenFormChildProps,
  ImageGenSubmitPayload,
} from "@/views/admin/ImageGenerationPage/forms/types";
import {
  ImageGenerationCredentials,
  ImageGenerationConfigView,
} from "@/views/admin/ImageGenerationPage/svc";
import { ImageProvider } from "@/views/admin/ImageGenerationPage/constants";

interface OpenAICompatibleFormValues {
  api_base: string;
  model_name: string;
  api_key: string;
}

const initialValues: OpenAICompatibleFormValues = {
  api_base: "",
  model_name: "gpt-image-1",
  api_key: "",
};

const validationSchema = Yup.object().shape({
  api_base: Yup.string()
    .required("Base URL is required")
    .test(
      "is-valid-url",
      "Must be a valid URL starting with http:// or https:// (e.g. http://localhost:7860/v1 or https://api.myprovider.com/v1)",
      (value) => {
        if (!value) return false;
        try {
          const parsed = new URL(value);
          return parsed.protocol === "http:" || parsed.protocol === "https:";
        } catch {
          return false;
        }
      }
    ),
  model_name: Yup.string().required("Model Name is required"),
  api_key: Yup.string().optional(),
});

function OpenAICompatibleFormFields(
  props: ImageGenFormChildProps<OpenAICompatibleFormValues>
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
      {/* Base URL Field */}
      <FormikField<string>
        name="api_base"
        render={(field, helper, meta, state) => (
          <FormField
            name="api_base"
            state={apiStatus === "error" ? "error" : state}
            className="w-full"
          >
            <FormField.Label>Base URL</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                onChange={(e) => {
                  field.onChange(e);
                  resetApiState();
                }}
                placeholder="https://api.myprovider.com/v1"
                variant={disabled ? "disabled" : undefined}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: "The target API base URL endpoint (e.g. http://localhost:7860/v1 or https://api.myprovider.com/v1)",
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />

      {/* Model Name Field */}
      <FormikField<string>
        name="model_name"
        render={(field, helper, meta, state) => (
          <FormField name="model_name" state={state} className="w-full">
            <FormField.Label>Model Name / ID</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                onChange={(e) => {
                  field.onChange(e);
                  resetApiState();
                }}
                placeholder="e.g. dall-e-3, flux-schnell, stablediffusion-xl"
                variant={disabled ? "disabled" : undefined}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: "Specify the model identifier requested by your endpoint.",
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />

      {/* API Key Field (Optional) */}
      <FormikField<string>
        name="api_key"
        render={(field, helper, meta, state) => (
          <FormField
            name="api_key"
            state={apiStatus === "error" ? "error" : state}
            className="w-full"
          >
            <FormField.Label>API Key (Optional)</FormField.Label>
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
                    isLoadingCredentials
                      ? "Loading..."
                      : "Optional (leave empty for local endpoints)"
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
                  loading: `Testing endpoint with ${imageProvider.title}...`,
                  success: "Provider configuration connected successfully.",
                  error: errorMessage || "Endpoint validation failed",
                }}
              />
            ) : (
              <FormField.Message
                messages={{
                  idle: "API key is optional for unauthenticated local deployments.",
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

function getInitialValuesFromCredentials(
  credentials: ImageGenerationCredentials,
  imageProvider: ImageProvider,
  existingConfig?: ImageGenerationConfigView
): Partial<OpenAICompatibleFormValues> {
  return {
    api_base: credentials.api_base || "",
    model_name: existingConfig?.model_name || imageProvider.model_name || "gpt-image-1",
    api_key: credentials.api_key || "",
  };
}

function transformValues(
  values: OpenAICompatibleFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  return {
    modelName: values.model_name || imageProvider.model_name,
    imageProviderId: imageProvider.image_provider_id,
    provider: "openai",
    apiBase: values.api_base,
    apiKey: values.api_key || undefined,
  };
}

export function OpenAICompatibleImageGenForm(props: ImageGenFormBaseProps) {
  const { imageProvider, existingConfig } = props;

  return (
    <ImageGenFormWrapper<OpenAICompatibleFormValues>
      {...props}
      title={
        existingConfig
          ? `Edit ${imageProvider.title}`
          : `Connect ${imageProvider.title}`
      }
      description={imageProvider.description}
      initialValues={initialValues}
      validationSchema={validationSchema}
      getInitialValuesFromCredentials={getInitialValuesFromCredentials}
      transformValues={(values) => transformValues(values, imageProvider)}
    >
      {(childProps) => <OpenAICompatibleFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
