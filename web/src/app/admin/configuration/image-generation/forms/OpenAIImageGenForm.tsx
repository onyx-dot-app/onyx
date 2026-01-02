"use client";

import React from "react";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { ImageGenFormWrapper } from "./ImageGenFormWrapper";
import {
  ImageGenFormBaseProps,
  ImageGenFormChildProps,
  ImageGenSubmitPayload,
} from "./types";
import { ImageGenerationCredentials } from "@/lib/configuration/imageConfigurationService";
import { ImageProvider } from "../constants";

// OpenAI form values - just API key
interface OpenAIFormValues {
  api_key: string;
}

const initialValues: OpenAIFormValues = {
  api_key: "",
};

const validationSchema = Yup.object().shape({
  api_key: Yup.string().required("API Key is required"),
});

function OpenAIFormFields(props: ImageGenFormChildProps<OpenAIFormValues>) {
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
                showClearButton={false}
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
                idle: "Enter a new API key or select an existing provider.",
                error: meta.error,
              }}
            />
          )}
        </FormField>
      )}
    />
  );
}

function getInitialValuesFromCredentials(
  credentials: ImageGenerationCredentials,
  _imageProvider: ImageProvider
): Partial<OpenAIFormValues> {
  return {
    api_key: credentials.api_key || "",
  };
}

function transformValues(
  values: OpenAIFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  return {
    modelName: imageProvider.model_name,
    imageProviderId: imageProvider.image_provider_id,
    provider: "openai",
    apiKey: values.api_key,
  };
}

export function OpenAIImageGenForm(props: ImageGenFormBaseProps) {
  const { imageProvider, existingConfig } = props;

  return (
    <ImageGenFormWrapper<OpenAIFormValues>
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
      {(childProps) => <OpenAIFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
