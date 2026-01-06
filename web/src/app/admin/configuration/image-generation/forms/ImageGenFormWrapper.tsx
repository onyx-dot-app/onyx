"use client";

import React, { useState, useMemo, useEffect } from "react";
import { Form, Formik, FormikProps } from "formik";
import ProviderModal from "@/components/modals/ProviderModal";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";
import ConnectionProviderIcon from "@/refresh-components/ConnectionProviderIcon";
import {
  testImageGenerationApiKey,
  createImageGenerationConfig,
  updateImageGenerationConfig,
  fetchImageGenerationCredentials,
} from "@/lib/configuration/imageConfigurationService";
import { APIFormFieldState } from "@/refresh-components/form/types";
import {
  ImageGenFormWrapperProps,
  ImageGenFormChildProps,
  ImageGenSubmitPayload,
  FormValues,
} from "./types";

export function ImageGenFormWrapper<T extends FormValues>({
  modal,
  imageProvider,
  existingProviders,
  existingConfig,
  onSuccess,
  setPopup,
  title,
  description,
  initialValues,
  validationSchema,
  children,
  transformValues,
  getInitialValuesFromCredentials,
}: ImageGenFormWrapperProps<T>) {
  // State management
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [apiStatus, setApiStatus] = useState<APIFormFieldState>("idle");
  const [showApiMessage, setShowApiMessage] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [isLoadingCredentials, setIsLoadingCredentials] = useState(false);

  // Form reset key for re-initialization
  const [formResetKey, setFormResetKey] = useState(0);

  // Track merged initial values with fetched credentials
  const [mergedInitialValues, setMergedInitialValues] =
    useState<T>(initialValues);

  const isEditMode = !!existingConfig;

  // Compute API key options from existing providers matching this image provider
  // API keys from LLM providers are already masked by backend (first 4 + **** + last 4)
  const apiKeyOptions = useMemo(() => {
    return existingProviders
      .filter((p) => p.provider === imageProvider.provider_name)
      .map((provider) => ({
        value: `existing:${provider.id}:${provider.name}`,
        label: provider.api_key || "****",
      }));
  }, [existingProviders, imageProvider.provider_name]);

  // Fetch credentials when modal opens in edit mode
  useEffect(() => {
    if (existingConfig && modal.isOpen) {
      setIsLoadingCredentials(true);
      fetchImageGenerationCredentials(existingConfig.image_provider_id)
        .then((creds) => {
          if (getInitialValuesFromCredentials) {
            const credValues = getInitialValuesFromCredentials(
              creds,
              imageProvider
            );
            setMergedInitialValues((prev) => ({ ...prev, ...credValues }));
            setFormResetKey((k) => k + 1);
          }
        })
        .catch((err) => {
          console.error("Failed to fetch credentials:", err);
        })
        .finally(() => {
          setIsLoadingCredentials(false);
        });
    } else if (!modal.isOpen) {
      // Reset when modal closes
      setMergedInitialValues(initialValues);
      setApiStatus("idle");
      setShowApiMessage(false);
      setErrorMessage("");
    }
  }, [
    existingConfig,
    modal.isOpen,
    getInitialValuesFromCredentials,
    imageProvider,
    initialValues,
  ]);

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

  const resetApiState = () => {
    if (showApiMessage) {
      setShowApiMessage(false);
      setApiStatus("idle");
      setErrorMessage("");
    }
  };

  const handleSubmit = async (values: T) => {
    setIsSubmitting(true);
    setShowApiMessage(true);
    setApiStatus("loading");

    try {
      // Get the submit payload from transformValues or use defaults
      const payload: ImageGenSubmitPayload = transformValues
        ? transformValues(values)
        : {
            modelName: imageProvider.model_name,
            imageProviderId: imageProvider.image_provider_id,
            provider: imageProvider.provider_name,
            apiKey: (values as Record<string, unknown>).api_key as
              | string
              | undefined,
          };

      // Check if user selected existing provider (clone mode)
      const apiKeyValue = (values as Record<string, unknown>).api_key as string;
      const isCloneMode = apiKeyValue?.startsWith("existing:");

      if (isCloneMode) {
        const parts = apiKeyValue.split(":");
        const providerIdStr = parts[1];
        if (!providerIdStr) {
          throw new Error("Invalid provider selection");
        }
        const providerId = parseInt(providerIdStr, 10);

        // Test API key from existing provider before creating config
        const result = await testImageGenerationApiKey(payload.modelName, {
          sourceLlmProviderId: providerId,
          apiBase: payload.apiBase,
          apiVersion: payload.apiVersion,
          deploymentName: payload.deploymentName,
        });

        if (!result.ok) {
          setApiStatus("error");
          setErrorMessage(result.errorMessage || "API key validation failed");
          setIsSubmitting(false);
          return;
        }

        // Test passed - now create/update config
        if (isEditMode && existingConfig) {
          await updateImageGenerationConfig(existingConfig.image_provider_id, {
            modelName: payload.modelName,
            sourceLlmProviderId: providerId,
            apiBase: payload.apiBase,
            apiVersion: payload.apiVersion,
            deploymentName: payload.deploymentName,
          });
        } else {
          await createImageGenerationConfig({
            imageProviderId: payload.imageProviderId,
            modelName: payload.modelName,
            sourceLlmProviderId: providerId,
            apiBase: payload.apiBase,
            apiVersion: payload.apiVersion,
            deploymentName: payload.deploymentName,
            isDefault: true,
          });
        }
      } else {
        // New credentials mode - check if API key was changed from masked value
        // A masked key contains "****", so if present, user hasn't entered a new key
        const apiKeyChanged = !apiKeyValue?.includes("****");

        // Test the API key first (only if changed or creating new config)
        if (apiKeyChanged) {
          const result = await testImageGenerationApiKey(payload.modelName, {
            provider: payload.provider,
            apiKey: payload.apiKey,
            apiBase: payload.apiBase,
            apiVersion: payload.apiVersion,
            deploymentName: payload.deploymentName,
          });

          if (!result.ok) {
            setApiStatus("error");
            setErrorMessage(result.errorMessage || "API key validation failed");
            setIsSubmitting(false);
            return;
          }
        }

        // Create or update config
        if (isEditMode && existingConfig) {
          await updateImageGenerationConfig(existingConfig.image_provider_id, {
            modelName: payload.modelName,
            provider: payload.provider,
            apiKey: payload.apiKey,
            apiBase: payload.apiBase,
            apiVersion: payload.apiVersion,
            deploymentName: payload.deploymentName,
            apiKeyChanged,
          });
        } else {
          await createImageGenerationConfig({
            imageProviderId: payload.imageProviderId,
            modelName: payload.modelName,
            provider: payload.provider,
            apiKey: payload.apiKey,
            apiBase: payload.apiBase,
            apiVersion: payload.apiVersion,
            deploymentName: payload.deploymentName,
            isDefault: true,
          });
        }
      }

      setApiStatus("success");
      setErrorMessage("");
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

  const icon = () => (
    <ConnectionProviderIcon
      icon={<ProviderIcon provider={imageProvider.provider_name} size={24} />}
    />
  );

  // Create child props
  const createChildProps = (
    formikProps: FormikProps<T>
  ): ImageGenFormChildProps<T> => ({
    formikProps,
    apiStatus,
    setApiStatus,
    showApiMessage,
    setShowApiMessage,
    errorMessage,
    setErrorMessage,
    isSubmitting,
    disabled: isSubmitting || isLoadingCredentials,
    isEditMode,
    isLoadingCredentials,
    apiKeyOptions,
    resetApiState,
    imageProvider,
  });

  return (
    <Formik<T>
      key={formResetKey}
      initialValues={mergedInitialValues}
      onSubmit={handleSubmit}
      validationSchema={validationSchema}
      enableReinitialize
    >
      {(formikProps) => {
        const childProps = createChildProps(formikProps);

        return (
          <ProviderModal
            open={modal.isOpen}
            onOpenChange={modal.toggle}
            title={title}
            description={description}
            icon={icon}
            onSubmit={formikProps.submitForm}
            submitDisabled={
              !formikProps.isValid ||
              (!isEditMode && !formikProps.dirty) ||
              isSubmitting
            }
            isSubmitting={isSubmitting}
          >
            <Form className="flex flex-col gap-0 bg-background-tint-01">
              <div className="flex flex-col gap-4 w-full">
                {children(childProps)}
              </div>
            </Form>
          </ProviderModal>
        );
      }}
    </Formik>
  );
}
