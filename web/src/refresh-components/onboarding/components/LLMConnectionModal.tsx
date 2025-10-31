import React, { useMemo, useState, useEffect } from "react";
import Modal from "@/refresh-components/modals/Modal";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import {
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";
import { Form, Formik, FormikProps } from "formik";
import { APIFormFieldState } from "@/refresh-components/form/types";
import Button from "@/refresh-components/buttons/Button";
import { MODAL_CONTENT_MAP, PROVIDER_TAB_CONFIG } from "../constants";
import { LLM_PROVIDERS_ADMIN_URL } from "@/app/admin/configuration/llm/constants";
import { fetchModels } from "@/app/admin/configuration/llm/utils";
import {
  buildInitialValues,
  getModelOptions,
  canProviderFetchModels,
  testApiKeyHelper,
} from "./llmConnectionHelpers";
import { LLMConnectionFieldsWithTabs } from "./LLMConnectionFieldsWithTabs";
import { LLMConnectionFieldsBasic } from "./LLMConnectionFieldsBasic";
import { getValidationSchema } from "./llmValidationSchema";
import { OnboardingActions, OnboardingState } from "../types";

type LLMConnectionModalData = {
  icon: React.ReactNode;
  title: string;
  llmDescriptor: WellKnownLLMProviderDescriptor;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
};

const LLMConnectionModal = () => {
  const { getModalData, toggleModal } = useChatModal();
  const data = getModalData<LLMConnectionModalData>();
  const icon = data?.icon;
  const title = data?.title ?? "";
  const llmDescriptor = data?.llmDescriptor;
  const modalContent = llmDescriptor
    ? MODAL_CONTENT_MAP[llmDescriptor.name]
    : undefined;
  const onboardingActions = data?.onboardingActions;
  const onboardingState = data?.onboardingState;

  const initialValues = useMemo(
    () => buildInitialValues(llmDescriptor),
    [llmDescriptor]
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
  const isApiError = apiStatus === "error";

  // Set default tab when llmDescriptor changes
  useEffect(() => {
    if (llmDescriptor) {
      const tabConfig = PROVIDER_TAB_CONFIG[llmDescriptor.name];
      if (tabConfig?.tabs[0]) {
        setActiveTab(tabConfig.tabs[0].id);
      }
      setFetchedModelConfigurations([]);
      setShowApiMessage(false);
      setErrorMessage("");
      setModelsErrorMessage("");
      setModelsApiStatus("loading");
      setShowModelsApiErrorMessage(false);
      setApiStatus("loading");
      setIsFetchingModels(false);
    }
  }, [llmDescriptor]);

  // Also reset when modal opens with new data
  useEffect(() => {
    if (data) {
      setFetchedModelConfigurations([]);
      setShowApiMessage(false);
      setErrorMessage("");
      setModelsErrorMessage("");
      setModelsApiStatus("loading");
      setShowModelsApiErrorMessage(false);
      setApiStatus("loading");
      setIsFetchingModels(false);
    }
  }, [data]);

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
    () => canProviderFetchModels(llmDescriptor),
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

  const testModelChangeWithApiKey = async (
    modelName: string,
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
      modelName
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

  if (!data) return null;

  const tabConfig = llmDescriptor
    ? PROVIDER_TAB_CONFIG[llmDescriptor.name]
    : null;

  return (
    <Modal
      id={ModalIds.LLMConnectionModal}
      title={title}
      description={modalContent?.description}
      startAdornment={icon}
      xs
    >
      <Formik
        initialValues={initialValues}
        validationSchema={getValidationSchema(llmDescriptor?.name, activeTab)}
        enableReinitialize
        onSubmit={async (values, { setSubmitting }) => {
          // Apply hidden fields based on active tab
          let finalValues = { ...values };
          if (tabConfig) {
            const currentTab = tabConfig.tabs.find((t) => t.id === activeTab);
            if (currentTab?.hiddenFields) {
              finalValues = { ...finalValues, ...currentTab.hiddenFields };
            }
          }

          // Use fetched model configurations if available
          const modelConfigsToUse =
            fetchedModelConfigurations.length > 0
              ? fetchedModelConfigurations
              : llmDescriptor?.model_configurations.map((model) => ({
                  name: model.name,
                  is_visible: true,
                  max_input_tokens: model.max_input_tokens,
                  supports_image_input: model.supports_image_input,
                })) ?? [];

          const payload = {
            ...initialValues,
            ...finalValues,
            model_configurations: modelConfigsToUse,
          };
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
                  console.error(
                    "Failed to set provider as default",
                    err?.detail
                  );
                }
              }
            } catch (_e) {
              console.error("Failed to set new provider as default", _e);
            }
          }
          onboardingActions?.updateData({
            llmProviders: [
              ...(onboardingState?.data.llmProviders ?? []),
              llmDescriptor?.name ?? "",
            ],
          });
          onboardingActions?.setButtonActive(true);
          toggleModal(ModalIds.LLMConnectionModal, false);
        }}
      >
        {(formikProps) => {
          // Apply hidden fields when tab changes
          useEffect(() => {
            if (tabConfig && activeTab) {
              const currentTab = tabConfig.tabs.find((t) => t.id === activeTab);
              setShowApiMessage(false);
              setErrorMessage("");
              setFetchedModelConfigurations([]);
              setModelsErrorMessage("");
              setModelsApiStatus("loading");
              setShowModelsApiErrorMessage(false);

              if (currentTab?.hiddenFields) {
                // Apply hidden fields for current tab
                Object.entries(currentTab.hiddenFields).forEach(
                  ([key, value]) => {
                    formikProps.setFieldValue(key, value);
                  }
                );
              } else {
                // Reset to defaults when switching to a tab without hidden fields
                if (
                  llmDescriptor?.default_api_base &&
                  formikProps.values.api_base !== llmDescriptor.default_api_base
                ) {
                  formikProps.setFieldValue(
                    "api_base",
                    llmDescriptor.default_api_base
                  );
                }
              }
            }
          }, [activeTab, tabConfig, llmDescriptor]);

          // Reset API message state when required fields become empty (provider-specific)
          useEffect(() => {
            if (!llmDescriptor) return;

            const values = formikProps.values as any;
            const isEmpty = (val: any) =>
              val == null || (typeof val === "string" && val.trim() === "");

            let shouldReset = false;
            switch (llmDescriptor.name) {
              case "openai":
              case "anthropic":
                if (isEmpty(values.api_key)) shouldReset = true;
                break;
              case "ollama":
                if (activeTab === "self-hosted") {
                  if (isEmpty(values.api_base)) shouldReset = true;
                } else if (activeTab === "cloud") {
                  if (isEmpty(values?.custom_config?.OLLAMA_API_KEY))
                    shouldReset = true;
                }
                break;
              case "azure":
                if (isEmpty(values.api_key) || isEmpty(values.target_uri))
                  shouldReset = true;
                break;
              case "openrouter":
                if (isEmpty(values.api_key) || isEmpty(values.api_base))
                  shouldReset = true;
                break;
              case "vertex_ai":
                if (isEmpty(values?.custom_config?.vertex_credentials))
                  shouldReset = true;
                break;
              case "bedrock":
                if (isEmpty(values?.custom_config?.AWS_REGION_NAME))
                  shouldReset = true;
                break;
              default:
                break;
            }

            if (shouldReset) {
              setShowApiMessage(false);
              setErrorMessage("");
              setModelsErrorMessage("");
              setModelsApiStatus("loading");
              setShowModelsApiErrorMessage(false);
              setApiStatus("loading");
              setFetchedModelConfigurations([]);
            }
          }, [
            llmDescriptor,
            activeTab,
            (formikProps.values as any).api_key,
            (formikProps.values as any).api_base,
            (formikProps.values as any).target_uri,
            (formikProps.values as any).custom_config,
          ]);

          const handleFetchModels = async () => {
            if (!llmDescriptor) return;

            await fetchModels(
              llmDescriptor,
              undefined, // existingLlmProvider
              formikProps.values,
              (field: string, value: any) => {
                // Custom setFieldValue to handle our state
                if (field === "fetched_model_configurations") {
                  setFetchedModelConfigurations(value);
                } else if (field === "default_model_name") {
                  formikProps.setFieldValue("default_model_name", value);
                  // Trigger validation of the newly set default model
                  if (value) {
                    testModelChangeWithApiKey(value, formikProps);
                  }
                } else if (field === "_modelListUpdated") {
                  // Ignore this field as it's just for forcing re-renders
                  return;
                } else {
                  formikProps.setFieldValue(field, value);
                }
              },
              setIsFetchingModels,
              setFetchModelsError
            );
          };

          return (
            <Form className="flex flex-col gap-0">
              <div className="flex flex-col p-4 gap-4 bg-background-tint-01 w-full">
                {tabConfig ? (
                  <LLMConnectionFieldsWithTabs
                    llmDescriptor={llmDescriptor!}
                    tabConfig={tabConfig}
                    modelOptions={modelOptions}
                    onApiKeyBlur={(apiKey) => testApiKey(apiKey, formikProps)}
                    showApiMessage={showApiMessage}
                    apiStatus={apiStatus}
                    errorMessage={errorMessage}
                    onFetchModels={handleFetchModels}
                    isFetchingModels={isFetchingModels}
                    canFetchModels={canFetchModels}
                    activeTab={activeTab}
                    setActiveTab={setActiveTab}
                    testModelChangeWithApiKey={(modelName) =>
                      testModelChangeWithApiKey(modelName, formikProps)
                    }
                    modelsApiStatus={modelsApiStatus}
                    modelsErrorMessage={modelsErrorMessage}
                    showModelsApiErrorMessage={showModelsApiErrorMessage}
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
                    onApiKeyBlur={(apiKey) => testApiKey(apiKey, formikProps)}
                    formikValues={formikProps.values}
                    setDefaultModelName={(value) =>
                      formikProps.setFieldValue("default_model_name", value)
                    }
                    onFetchModels={handleFetchModels}
                    canFetchModels={canFetchModels}
                    modelsApiStatus={modelsApiStatus}
                    modelsErrorMessage={modelsErrorMessage}
                    showModelsApiErrorMessage={showModelsApiErrorMessage}
                    testModelChangeWithApiKey={(modelName) =>
                      testModelChangeWithApiKey(modelName, formikProps)
                    }
                    testFileInputChange={(customConfig) =>
                      testFileInputChange(customConfig, formikProps)
                    }
                  />
                )}
              </div>
              <div className="flex justify-end gap-2 w-full p-4">
                <Button
                  type="button"
                  secondary
                  onClick={() =>
                    toggleModal(ModalIds.LLMConnectionModal, false)
                  }
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={
                    apiStatus != "success" ||
                    !formikProps.isValid ||
                    !formikProps.dirty
                  }
                >
                  Connect
                </Button>
              </div>
            </Form>
          );
        }}
      </Formik>
    </Modal>
  );
};

export default LLMConnectionModal;
