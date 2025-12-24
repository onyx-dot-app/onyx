import React, { useMemo, useState, useEffect } from "react";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { Form, Formik, FormikProps, useFormikContext } from "formik";
import { APIFormFieldState } from "@/refresh-components/form/types";
import { MODAL_CONTENT_MAP, PROVIDER_TAB_CONFIG } from "../constants";
import { LLM_PROVIDERS_ADMIN_URL } from "@/app/admin/configuration/llm/constants";
import { parseAzureTargetUri } from "@/lib/azureTargetUri";
import {
  canProviderFetchModels,
  fetchModels,
} from "@/app/admin/configuration/llm/utils";
import {
  buildInitialValues,
  getModelOptions,
  testApiKeyHelper,
  testCustomProvider,
} from "./llmConnectionHelpers";
import { LLMConnectionFieldsWithTabs } from "./LLMConnectionFieldsWithTabs";
import LLMConnectionFieldsBasic from "./LLMConnectionFieldsBasic";
import { LLMConnectionFieldsCustom } from "./LLMConnectionFieldsCustom";
import { getValidationSchema } from "./llmValidationSchema";
import { OnboardingActions, OnboardingState } from "../types";
import LLMFormikEffects from "./LLMFormikEffects";

import ProviderModal from "@/components/modals/ProviderModal";
import { ModalCreationInterface } from "@/refresh-components/contexts/ModalContext";

export interface LLMConnectionModalProps {
  icon: React.ReactNode;
  title: string;
  llmDescriptor?: WellKnownLLMProviderDescriptor;
  isCustomProvider?: boolean;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  modal: ModalCreationInterface;
}

export default function LLMConnectionModal({
  icon,
  title,
  llmDescriptor,
  isCustomProvider,
  onboardingState,
  onboardingActions,
  modal,
}: LLMConnectionModalProps) {
  const modalContent = isCustomProvider
    ? MODAL_CONTENT_MAP["custom"]
    : llmDescriptor
      ? MODAL_CONTENT_MAP[llmDescriptor.name]
      : undefined;

  const initialValues = useMemo(
    () => buildInitialValues(llmDescriptor, isCustomProvider),
    [llmDescriptor, isCustomProvider]
  );

  const [apiStatus, setApiStatus] = useState<APIFormFieldState>("loading");
  const [showApiMessage, setShowApiMessage] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [modelsErrorMessage, setModelsErrorMessage] = useState<string>("");
  const [modelsApiStatus, setModelsApiStatus] =
    useState<APIFormFieldState>("loading");
  const [showModelsApiErrorMessage, setShowModelsApiErrorMessage] =
    useState(false);
  const [activeTab, setActiveTab] = useState<string>("");
  const [isFetchingModels, setIsFetchingModels] = useState(false);
  const [fetchedModelConfigurations, setFetchedModelConfigurations] = useState<
    any[]
  >([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formResetKey, setFormResetKey] = useState(0);

  const modelOptions = useMemo(
    () => getModelOptions(llmDescriptor, fetchedModelConfigurations as any[]),
    [llmDescriptor, fetchedModelConfigurations]
  );

  useEffect(() => {
    if (fetchedModelConfigurations.length > 0 && !isFetchingModels) {
      setModelsApiStatus("success");
    }
  }, [fetchedModelConfigurations, isFetchingModels]);

  const canFetchModels = useMemo(
    () => canProviderFetchModels(llmDescriptor?.name),
    [llmDescriptor]
  );

  const setFetchModelsError = (error: string) => {
    setModelsApiStatus("loading");
    setShowModelsApiErrorMessage(true);
    setModelsErrorMessage(error);
    if (error) {
      setModelsApiStatus("error");
    }
  };

  const testApiKey = async (apiKey: string, formikProps: FormikProps<any>) => {
    setApiStatus("loading");
    setShowApiMessage(true);
    if (!llmDescriptor) {
      setApiStatus("error");
      return;
    }
    const result = await testApiKeyHelper(
      llmDescriptor,
      initialValues,
      formikProps.values,
      apiKey
    );
    if (result.ok) {
      setApiStatus("success");
    } else {
      setErrorMessage(result.errorMessage);
      setApiStatus("error");
    }
  };

  const testFileInputChange = async (
    customConfig: Record<string, any>,
    formikProps: FormikProps<any>
  ) => {
    if (!llmDescriptor) return;
    setApiStatus("loading");
    setShowApiMessage(true);
    const result = await testApiKeyHelper(
      llmDescriptor,
      initialValues,
      formikProps.values,
      undefined,
      undefined,
      customConfig
    );
    if (result.ok) {
      setApiStatus("success");
    } else {
      setErrorMessage(result.errorMessage);
      setApiStatus("error");
    }
  };

  const tabConfig = llmDescriptor
    ? PROVIDER_TAB_CONFIG[llmDescriptor.name]
    : null;

  // Initialize activeTab to the first tab if tabConfig exists
  useEffect(() => {
    const firstTabId = tabConfig?.tabs?.[0]?.id;
    if (firstTabId && !activeTab) {
      setActiveTab(firstTabId);
    }
  }, [tabConfig, activeTab]);

  // Reset when modal opens to ensure fresh form
  useEffect(() => {
    if (modal.isOpen) {
      setFormResetKey((prev) => prev + 1);
    }
  }, [modal.isOpen]);

  return (
    <Formik
      key={formResetKey}
      initialValues={initialValues}
      validationSchema={getValidationSchema(
        isCustomProvider ? "custom" : llmDescriptor?.name,
        activeTab
      )}
      enableReinitialize
      onSubmit={async (values, { setSubmitting }) => {
        setIsSubmitting(true);
        // Apply hidden fields based on active tab
        let finalValues = { ...values };
        if (tabConfig) {
          const currentTab = tabConfig.tabs.find((t) => t.id === activeTab);
          if (currentTab?.hiddenFields) {
            finalValues = { ...finalValues, ...currentTab.hiddenFields };
          }
        }

        // Use fetched model configurations if available
        let modelConfigsToUse =
          fetchedModelConfigurations.length > 0
            ? fetchedModelConfigurations
            : llmDescriptor?.model_configurations.map((model) => ({
                name: model.name,
                is_visible: true,
                max_input_tokens: model.max_input_tokens,
                supports_image_input: model.supports_image_input,
              })) ?? [];

        // For custom providers, use the values from the form and filter out empty entries
        if (isCustomProvider) {
          modelConfigsToUse = (finalValues.model_configurations || []).filter(
            (config: any) => config.name && config.name.trim() !== ""
          );

          // Filter out empty custom config entries
          const filteredCustomConfig: Record<string, string> = {};
          Object.entries(finalValues.custom_config || {}).forEach(
            ([key, value]) => {
              if (key.trim() !== "") {
                filteredCustomConfig[key] = value as string;
              }
            }
          );
          finalValues.custom_config = filteredCustomConfig;
        }

        const payload = {
          ...initialValues,
          ...finalValues,
          model_configurations: modelConfigsToUse,
        };

        // Azure OpenAI: derive required fields from the single Target URI input
        if (llmDescriptor?.name === "azure" && payload?.target_uri) {
          try {
            const { url, apiVersion, deploymentName } = parseAzureTargetUri(
              payload.target_uri
            );
            payload.api_base = url.origin;
            payload.api_version = apiVersion;
            if (deploymentName) {
              payload.deployment_name = deploymentName;
            }
          } catch (error) {
            // Should be prevented by validation, but handle gracefully.
            console.error("Failed to parse target_uri:", error);
          }
        }

        setApiStatus("loading");
        setShowApiMessage(true);
        let result;

        if (llmDescriptor) {
          result = await testApiKeyHelper(
            llmDescriptor,
            initialValues,
            payload
          );
        } else {
          result = await testCustomProvider(payload);
        }
        if (!result.ok) {
          setErrorMessage(result.errorMessage);
          setApiStatus("error");
          setIsSubmitting(false);
          return;
        }
        setApiStatus("success");

        const response = await fetch(
          `${LLM_PROVIDERS_ADMIN_URL}${"?is_creation=true"}`,
          {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
          }
        );
        if (!response.ok) {
          const errorMsg = (await response.json()).detail;
          console.error("Failed to create LLM provider", errorMsg);
          setIsSubmitting(false);
          return;
        }
        // If this is the first LLM provider, set it as the default provider
        if (onboardingState?.data?.llmProviders == null) {
          try {
            const newLlmProvider = await response.json();
            if (newLlmProvider?.id != null) {
              const setDefaultResponse = await fetch(
                `${LLM_PROVIDERS_ADMIN_URL}/${newLlmProvider.id}/default`,
                { method: "POST" }
              );
              if (!setDefaultResponse.ok) {
                const err = await setDefaultResponse.json().catch(() => ({}));
                console.error("Failed to set provider as default", err?.detail);
              }
            }
          } catch (_e) {
            console.error("Failed to set new provider as default", _e);
          }
        }
        onboardingActions?.updateData({
          llmProviders: [
            ...(onboardingState?.data.llmProviders ?? []),
            isCustomProvider ? "custom" : llmDescriptor?.name ?? "",
          ],
        });
        onboardingActions?.setButtonActive(true);
        setIsSubmitting(false);
        modal.toggle(false);
      }}
    >
      {(formikProps) => {
        const handleFetchModels = async () => {
          if (!llmDescriptor) return;

          setIsFetchingModels(true);
          const { models, error } = await fetchModels(
            llmDescriptor.name,
            formikProps.values
          );
          if (error) {
            setFetchModelsError(error);
          } else {
            setFetchedModelConfigurations(models);
          }
        };
        setIsFetchingModels(false);

        return (
          <ProviderModal
            open={modal.isOpen}
            onOpenChange={modal.toggle}
            title={title}
            description={modalContent?.description}
            icon={() => icon}
            onSubmit={formikProps.submitForm}
            submitDisabled={
              isCustomProvider
                ? !formikProps.isValid || !formikProps.dirty
                : !formikProps.isValid || !formikProps.dirty
            }
            isSubmitting={isSubmitting}
          >
            <LLMFormikEffects
              tabConfig={tabConfig}
              activeTab={activeTab}
              llmDescriptor={llmDescriptor}
              setShowApiMessage={setShowApiMessage}
              setErrorMessage={setErrorMessage}
              setFetchedModelConfigurations={setFetchedModelConfigurations}
              setModelsErrorMessage={setModelsErrorMessage}
              setModelsApiStatus={setModelsApiStatus}
              setShowModelsApiErrorMessage={setShowModelsApiErrorMessage}
              setApiStatus={setApiStatus}
            />
            <Form className="flex flex-col gap-0">
              <div className="flex flex-col p-4 gap-4 bg-background-tint-01 w-full">
                {isCustomProvider ? (
                  <LLMConnectionFieldsCustom
                    showApiMessage={showApiMessage}
                    apiStatus={apiStatus}
                    errorMessage={errorMessage}
                    disabled={isSubmitting}
                  />
                ) : tabConfig ? (
                  <LLMConnectionFieldsWithTabs
                    llmDescriptor={llmDescriptor!}
                    tabConfig={tabConfig}
                    modelOptions={modelOptions}
                    showApiMessage={showApiMessage}
                    apiStatus={apiStatus}
                    errorMessage={errorMessage}
                    onFetchModels={handleFetchModels}
                    isFetchingModels={isFetchingModels}
                    canFetchModels={canFetchModels}
                    activeTab={activeTab}
                    setActiveTab={setActiveTab}
                    modelsApiStatus={modelsApiStatus}
                    modelsErrorMessage={modelsErrorMessage}
                    showModelsApiErrorMessage={showModelsApiErrorMessage}
                    disabled={isSubmitting}
                  />
                ) : (
                  <LLMConnectionFieldsBasic
                    llmDescriptor={llmDescriptor!}
                    modalContent={modalContent}
                    modelOptions={modelOptions}
                    showApiMessage={showApiMessage}
                    apiStatus={apiStatus}
                    errorMessage={errorMessage}
                    isFetchingModels={isFetchingModels}
                    formikValues={formikProps.values}
                    setDefaultModelName={(value) =>
                      formikProps.setFieldValue("default_model_name", value)
                    }
                    onFetchModels={handleFetchModels}
                    canFetchModels={canFetchModels}
                    modelsApiStatus={modelsApiStatus}
                    modelsErrorMessage={modelsErrorMessage}
                    showModelsApiErrorMessage={showModelsApiErrorMessage}
                    testFileInputChange={(customConfig) =>
                      testFileInputChange(customConfig, formikProps)
                    }
                    disabled={isSubmitting}
                  />
                )}
              </div>
            </Form>
          </ProviderModal>
        );
      }}
    </Formik>
  );
}
