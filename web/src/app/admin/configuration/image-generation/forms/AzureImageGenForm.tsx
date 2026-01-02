"use client";

import React from "react";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
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
import {
  parseAzureTargetUri,
  isValidAzureTargetUri,
} from "@/lib/azureTargetUri";

// Azure form values - target URI and API key
interface AzureFormValues {
  target_uri: string;
  api_key: string;
}

const initialValues: AzureFormValues = {
  target_uri: "",
  api_key: "",
};

const validationSchema = Yup.object().shape({
  target_uri: Yup.string()
    .required("Target URI is required")
    .test(
      "valid-target-uri",
      "Target URI must be a valid URL with api-version and deployment name",
      (value) => (value ? isValidAzureTargetUri(value) : false)
    ),
  api_key: Yup.string().required("API Key is required"),
});

function AzureFormFields(props: ImageGenFormChildProps<AzureFormValues>) {
  const {
    formikProps,
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
      {/* Target URI field */}
      <FormikField<string>
        name="target_uri"
        render={(field, helper, meta, state) => (
          <FormField name="target_uri" state={state} className="w-full">
            <FormField.Label>Target URI</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                placeholder="https://your-resource.cognitiveservices.azure.com/openai/deployments/deployment-name/images/generations?api-version=2025-01-01-preview"
                showClearButton={false}
                disabled={disabled}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: (
                  <>
                    Paste your endpoint target URI from{" "}
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

      {/* API Key field */}
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
                  disabled={disabled || !formikProps.values.target_uri?.trim()}
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
                  disabled={disabled || !formikProps.values.target_uri?.trim()}
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
                  idle: (
                    <>
                      {"Paste your "}
                      <a
                        href="https://oai.azure.com"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline"
                      >
                        API key
                      </a>
                      {" from Azure OpenAI to access your models."}
                    </>
                  ),
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
  imageProvider: ImageProvider
): Partial<AzureFormValues> {
  // Reconstruct target_uri from credentials
  let targetUri = "";
  if (credentials.api_base && credentials.api_version) {
    const deployment = credentials.deployment_name || imageProvider.model_name;
    targetUri = `${credentials.api_base}/openai/deployments/${deployment}/images/generations?api-version=${credentials.api_version}`;
  }

  return {
    api_key: credentials.api_key || "",
    target_uri: targetUri,
  };
}

function transformValues(
  values: AzureFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  // Parse target_uri to extract api_base, api_version, deployment_name
  let apiBase: string | undefined;
  let apiVersion: string | undefined;
  let deploymentName: string | undefined;
  let modelName = imageProvider.model_name;

  if (values.target_uri) {
    try {
      const parsed = parseAzureTargetUri(values.target_uri);
      apiBase = parsed.url.origin;
      apiVersion = parsed.apiVersion;
      deploymentName = parsed.deploymentName || undefined;
      // For Azure, use deployment name as model name
      modelName = deploymentName || imageProvider.model_name;
    } catch (error) {
      console.error("Failed to parse target_uri:", error);
    }
  }

  return {
    modelName,
    imageProviderId: imageProvider.image_provider_id,
    provider: "azure",
    apiKey: values.api_key,
    apiBase,
    apiVersion,
    deploymentName,
  };
}

export function AzureImageGenForm(props: ImageGenFormBaseProps) {
  const { imageProvider, existingConfig } = props;

  return (
    <ImageGenFormWrapper<AzureFormValues>
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
      {(childProps) => <AzureFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
