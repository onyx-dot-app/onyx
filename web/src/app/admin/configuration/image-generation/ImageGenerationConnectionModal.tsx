"use client";

import React, { useState, useMemo, useEffect } from "react";
import { Form, Formik } from "formik";
import ProviderModal from "@/components/modals/ProviderModal";
import { ModalCreationInterface } from "@/refresh-components/contexts/ModalContext";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import {
  LLMProviderView,
  WellKnownLLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";
import { ImageProvider } from "./constants";
import { MODAL_CONTENT_MAP } from "@/refresh-components/onboarding/constants";
import { parseAzureTargetUri } from "@/lib/azureTargetUri";
import {
  testImageGenerationApiKey,
  createImageGenerationConfig,
  updateImageGenerationConfig,
  fetchImageGenerationCredentials,
  ImageGenerationConfigView,
  ImageGenerationCredentials,
} from "@/lib/configuration/imageConfigurationService";
import { PopupSpec } from "@/components/admin/connectors/Popup";

interface Props {
  modal: ModalCreationInterface;
  imageProvider: ImageProvider;
  llmDescriptor?: WellKnownLLMProviderDescriptor;
  existingProviders: LLMProviderView[];
  existingConfig?: ImageGenerationConfigView; // For edit mode
  onSuccess: () => void;
  setPopup: (popup: PopupSpec | null) => void;
}

type APIStatus = "idle" | "loading" | "success" | "error";

export default function ImageGenerationConnectionModal({
  modal,
  imageProvider,
  llmDescriptor,
  existingProviders,
  existingConfig,
  onSuccess,
  setPopup,
}: Props) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [apiStatus, setApiStatus] = useState<APIStatus>("idle");
  const [showApiMessage, setShowApiMessage] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  // State for fetched credentials in edit mode
  const [fetchedCredentials, setFetchedCredentials] =
    useState<ImageGenerationCredentials | null>(null);
  const [isLoadingCredentials, setIsLoadingCredentials] = useState(false);

  // Determine if we're in edit mode
  const isEditMode = !!existingConfig;

  // Use llmDescriptor.name to determine if this is Azure
  const isAzure = llmDescriptor?.name === "azure";

  // Fetch credentials when modal opens in edit mode
  useEffect(() => {
    if (existingConfig && modal.isOpen) {
      setIsLoadingCredentials(true);
      fetchImageGenerationCredentials(existingConfig.id)
        .then((creds) => {
          setFetchedCredentials(creds);
        })
        .catch((err) => {
          console.error("Failed to fetch credentials:", err);
        })
        .finally(() => {
          setIsLoadingCredentials(false);
        });
    } else if (!modal.isOpen) {
      // Reset when modal closes
      setFetchedCredentials(null);
    }
  }, [existingConfig, modal.isOpen]);

  // Close modal after successful connection (1 second delay)
  useEffect(() => {
    if (apiStatus === "success" && !isSubmitting) {
      const timer = setTimeout(() => {
        onSuccess();
        modal.toggle(false);
      }, 1000);
      return () => clearTimeout(timer);
    }
  }, [apiStatus, isSubmitting, modal, onSuccess]);

  // Get field metadata from MODAL_CONTENT_MAP using descriptor name
  const modalContent = llmDescriptor?.name
    ? MODAL_CONTENT_MAP[llmDescriptor.name]
    : undefined;

  // Filter providers that match this image provider's provider_name
  const matchingProviders = useMemo(() => {
    return existingProviders.filter(
      (p) => p.provider === imageProvider.provider_name
    );
  }, [existingProviders, imageProvider.provider_name]);

  // Build combobox options with provider names (API keys are masked by backend)
  const apiKeyOptions = useMemo(() => {
    return matchingProviders.map((provider) => ({
      value: `existing:${provider.id}:${provider.name}`,
      label: `${provider.api_key || "••••"}`,
    }));
  }, [matchingProviders]);

  // Initial values - use fetched credentials in edit mode
  const initialValues = useMemo(() => {
    if (isEditMode && fetchedCredentials) {
      // For Azure, reconstruct target_uri from credentials
      let targetUri = "";
      if (
        isAzure &&
        fetchedCredentials.api_base &&
        fetchedCredentials.api_version
      ) {
        const deployment =
          fetchedCredentials.deployment_name || imageProvider.id;
        targetUri = `${fetchedCredentials.api_base}/openai/deployments/${deployment}/images/generations?api-version=${fetchedCredentials.api_version}`;
      }

      return {
        api_key: fetchedCredentials.api_key || "",
        api_base: fetchedCredentials.api_base || "",
        target_uri: targetUri,
      };
    }
    return {
      api_key: "",
      api_base: "",
      target_uri: "",
    };
  }, [isEditMode, fetchedCredentials, isAzure, imageProvider.id]);

  // Track initial API key for change detection
  const initialApiKey = fetchedCredentials?.api_key || "";

  // Handle form submit - test API key and create/update config
  const handleSubmit = async (values: typeof initialValues) => {
    setIsSubmitting(true);
    setShowApiMessage(true);
    setApiStatus("loading");

    try {
      // Check if user kept same API key (no changes) in edit mode
      if (isEditMode && existingConfig && values.api_key === initialApiKey) {
        // No changes - just close modal
        setApiStatus("success");
        setIsSubmitting(false);
        return;
      }

      // Check if user selected existing provider (clone mode)
      if (values.api_key.startsWith("existing:")) {
        const parts = values.api_key.split(":");
        const providerIdStr = parts[1];
        if (!providerIdStr) {
          throw new Error("Invalid provider selection");
        }
        const providerId = parseInt(providerIdStr, 10);

        if (isEditMode && existingConfig) {
          // Update mode: Backend deletes old provider and creates new one
          await updateImageGenerationConfig(existingConfig.id, {
            modelName: imageProvider.id,
            sourceLlmProviderId: providerId,
          });
        } else {
          // Create mode: Backend creates new provider
          await createImageGenerationConfig({
            modelName: imageProvider.id,
            sourceLlmProviderId: providerId,
            isDefault: false,
          });
        }

        setApiStatus("success");
      } else {
        // User entered new API key - test it first
        let apiBase = values.api_base;
        let apiVersion: string | undefined;
        let deploymentName: string | undefined;

        if (isAzure && values.target_uri) {
          try {
            const parsed = parseAzureTargetUri(values.target_uri);
            apiBase = parsed.url.origin;
            apiVersion = parsed.apiVersion;
            deploymentName = parsed.deploymentName || undefined;
          } catch {
            setApiStatus("error");
            setErrorMessage("Invalid Azure Target URI");
            setIsSubmitting(false);
            return;
          }
        }

        // Test API key
        const result = await testImageGenerationApiKey(
          imageProvider.provider_name,
          values.api_key,
          imageProvider.id,
          apiBase || undefined,
          apiVersion,
          deploymentName
        );

        if (!result.ok) {
          setApiStatus("error");
          setErrorMessage(result.errorMessage || "API key validation failed");
          setIsSubmitting(false);
          return;
        }

        // API key valid - show success message
        setApiStatus("success");
        setErrorMessage("");

        if (isEditMode && existingConfig) {
          // Update mode: Backend deletes old provider and creates new one
          await updateImageGenerationConfig(existingConfig.id, {
            modelName: imageProvider.id,
            provider: imageProvider.provider_name,
            apiKey: values.api_key,
            apiBase: apiBase || undefined,
            apiVersion,
            deploymentName,
          });
        } else {
          // Create mode: Backend creates new provider
          await createImageGenerationConfig({
            modelName: imageProvider.id,
            provider: imageProvider.provider_name,
            apiKey: values.api_key,
            apiBase: apiBase || undefined,
            apiVersion,
            deploymentName,
            isDefault: false,
          });
        }
      }

      // Reset isSubmitting so useEffect can close the modal
      setIsSubmitting(false);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown error occurred";
      setApiStatus("error");
      setErrorMessage(message);
      setPopup({ message, type: "error" });
      setIsSubmitting(false);
    }
  };

  const resetApiState = () => {
    if (showApiMessage) {
      setShowApiMessage(false);
      setApiStatus("idle");
      setErrorMessage("");
    }
  };

  return (
    <Formik
      initialValues={initialValues}
      onSubmit={handleSubmit}
      enableReinitialize
    >
      {(formikProps) => (
        <ProviderModal
          open={modal.isOpen}
          onOpenChange={modal.toggle}
          title={
            isEditMode
              ? `Edit ${imageProvider.title}`
              : `Connect ${imageProvider.title}`
          }
          description={imageProvider.description}
          icon={() => <imageProvider.icon className="size-5" />}
          onSubmit={formikProps.submitForm}
          submitDisabled={
            (!isEditMode && !formikProps.dirty) || apiStatus === "loading"
          }
          isSubmitting={isSubmitting}
        >
          <Form className="flex flex-col gap-0 bg-background-tint-01">
            <div className="flex flex-col p-4 gap-4 w-full">
              {/* Azure-specific Target URI field */}
              {isAzure && (
                <FormikField<string>
                  name="target_uri"
                  render={(field, helper, meta, state) => (
                    <FormField
                      name="target_uri"
                      state={state}
                      className="w-full"
                    >
                      <FormField.Label>Target URI</FormField.Label>
                      <FormField.Control>
                        <InputTypeIn
                          {...field}
                          placeholder="https://your-resource.cognitiveservices.azure.com/openai/deployments/deployment-name/chat/completions?api-version=2025-01-01-preview"
                          showClearButton={false}
                          disabled={isSubmitting}
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
                              (including API endpoint base, deployment name, and
                              API version).
                            </>
                          ),
                          error: meta.error,
                        }}
                      />
                    </FormField>
                  )}
                />
              )}

              {/* API Key field - render if descriptor requires it (or if no descriptor, always show) */}
              {(llmDescriptor?.api_key_required ?? true) && (
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
                            disabled={isSubmitting || isLoadingCredentials}
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
                                : "Enter your API key"
                            }
                            showClearButton={false}
                            disabled={isSubmitting || isLoadingCredentials}
                            error={apiStatus === "error"}
                          />
                        )}
                      </FormField.Control>
                      {/* Show API message (loading/success/error) when testing */}
                      {showApiMessage ? (
                        <FormField.APIMessage
                          state={apiStatus}
                          messages={{
                            loading: `Testing API key with ${
                              modalContent?.display_name || imageProvider.title
                            }...`,
                            success:
                              "API key is valid. Your available models updated.",
                            error: errorMessage || "Invalid API key",
                          }}
                        />
                      ) : (
                        <FormField.Message
                          messages={{
                            idle:
                              modalContent?.field_metadata?.api_key ||
                              "Enter a new API key or select an existing provider.",
                            error: meta.error,
                          }}
                        />
                      )}
                    </FormField>
                  )}
                />
              )}
            </div>
          </Form>
        </ProviderModal>
      )}
    </Formik>
  );
}
