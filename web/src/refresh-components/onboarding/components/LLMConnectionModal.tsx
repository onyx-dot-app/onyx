import React, { useMemo, useState, useEffect } from "react";
import Modal from "@/refresh-components/modals/Modal";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
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

type LLMConnectionModalData = {
  icon: React.ReactNode;
  title: string;
  llmDescriptor: WellKnownLLMProviderDescriptor;
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

  const initialValues = useMemo(
    () => buildInitialValues(llmDescriptor),
    [llmDescriptor]
  );

  const [apiStatus, setApiStatus] = useState<APIFormFieldState>("loading");
  const [showApiMessage, setShowApiMessage] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>("");
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
      setApiStatus("loading");
      setIsFetchingModels(false);
    }
  }, [data]);

  // Get model options - use fetched models if available, otherwise use descriptor models
  const modelOptions = useMemo(
    () => getModelOptions(llmDescriptor, fetchedModelConfigurations as any[]),
    [llmDescriptor, fetchedModelConfigurations]
  );

  useEffect(() => {
    if (fetchedModelConfigurations.length > 0 && !isFetchingModels) {
      setApiStatus("success");
    }
  }, [fetchedModelConfigurations, isFetchingModels]);

  // Check if provider supports dynamic model fetching
  const canFetchModels = useMemo(
    () => canProviderFetchModels(llmDescriptor),
    [llmDescriptor]
  );

  const setFetchModelsError = (error: string) => {
    setApiStatus("loading");
    setShowApiMessage(true);
    setErrorMessage(error);
    if (error) {
      setApiStatus("error");
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
          console.log("payload", payload);
          const response = await fetch(
            `${LLM_PROVIDERS_ADMIN_URL}${"?is_creation=true"}`,
            {
              method: "PUT",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                ...payload,
              }),
            }
          );
          if (!response.ok) {
            const errorMsg = (await response.json()).detail;
            console.log("errorMsg", errorMsg);
            return;
          }

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
                <Button type="submit">Connect</Button>
              </div>
            </Form>
          );
        }}
      </Formik>
    </Modal>
  );
};

export default LLMConnectionModal;
