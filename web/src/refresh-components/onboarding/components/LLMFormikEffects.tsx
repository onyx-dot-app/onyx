import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { APIFormFieldState } from "@/refresh-components/form/types";
import { useFormikContext } from "formik";
import { useEffect } from "react";
import { LLMProviderName } from "@/app/admin/configuration/llm/interfaces";

type LLMFormikEffectsProps = {
  tabConfig: any;
  activeTab: string;
  llmDescriptor?: WellKnownLLMProviderDescriptor;
  setShowApiMessage: (v: boolean) => void;
  setErrorMessage: (v: string) => void;
  setFetchedModelConfigurations: (v: any[]) => void;
  setModelsErrorMessage: (v: string) => void;
  setModelsApiStatus: (v: APIFormFieldState) => void;
  setShowModelsApiErrorMessage: (v: boolean) => void;
  setApiStatus: (v: APIFormFieldState) => void;
};

const LLMFormikEffects = ({
  tabConfig,
  activeTab,
  llmDescriptor,
  setShowApiMessage,
  setErrorMessage,
  setFetchedModelConfigurations,
  setModelsErrorMessage,
  setModelsApiStatus,
  setShowModelsApiErrorMessage,
  setApiStatus,
}: LLMFormikEffectsProps) => {
  const formikProps = useFormikContext<any>();

  useEffect(() => {
    if (tabConfig && activeTab) {
      const currentTab = tabConfig.tabs.find((t: any) => t.id === activeTab);
      setShowApiMessage(false);
      setErrorMessage("");
      setFetchedModelConfigurations([]);
      setModelsErrorMessage("");
      setModelsApiStatus("loading");
      setShowModelsApiErrorMessage(false);

      // Clear fields when switching Ollama tabs
      if (llmDescriptor?.name === LLMProviderName.OLLAMA_CHAT) {
        if (activeTab === "self-hosted") {
          formikProps.setFieldValue("custom_config.OLLAMA_API_KEY", "");
        }
      }

      if (currentTab?.hiddenFields) {
        Object.entries(currentTab.hiddenFields).forEach(([key, value]) => {
          formikProps.setFieldValue(key, value);
        });
      } else {
        //set default api base when tab changes
        if (
          llmDescriptor?.default_api_base &&
          formikProps.values.api_base !== llmDescriptor.default_api_base
        ) {
          formikProps.setFieldValue("api_base", llmDescriptor.default_api_base);
        }
      }
    }
  }, [activeTab, tabConfig, llmDescriptor]);

  useEffect(() => {
    if (!llmDescriptor) return;

    const values = formikProps.values as any;
    const isEmpty = (val: any) =>
      val == null || (typeof val === "string" && val.trim() === "");

    let shouldReset = false;
    switch (llmDescriptor.name) {
      case LLMProviderName.OPENAI:
      case LLMProviderName.ANTHROPIC:
        if (isEmpty(values.api_key)) shouldReset = true;
        break;
      case LLMProviderName.OLLAMA_CHAT:
        if (activeTab === "self-hosted") {
          if (isEmpty(values.api_base)) shouldReset = true;
        } else if (activeTab === "cloud") {
          if (isEmpty(values?.custom_config?.OLLAMA_API_KEY))
            shouldReset = true;
        }
        break;
      case LLMProviderName.AZURE:
        if (isEmpty(values.api_key) || isEmpty(values.target_uri))
          shouldReset = true;
        break;
      case LLMProviderName.OPENROUTER:
        if (isEmpty(values.api_key) || isEmpty(values.api_base))
          shouldReset = true;
        break;
      case LLMProviderName.VERTEX_AI:
        if (isEmpty(values?.custom_config?.vertex_credentials))
          shouldReset = true;
        break;
      case LLMProviderName.BEDROCK: {
        const selectedAuth = values?.custom_config?.BEDROCK_AUTH_METHOD;
        if (selectedAuth === "access_key") {
          formikProps.setFieldValue(
            "custom_config.AWS_BEARER_TOKEN_BEDROCK",
            ""
          );
          shouldReset = true;
        } else if (selectedAuth === "long_term_api_key") {
          formikProps.setFieldValue("custom_config.AWS_ACCESS_KEY_ID", "");
          formikProps.setFieldValue("custom_config.AWS_SECRET_ACCESS_KEY", "");
          shouldReset = true;
        } else if (selectedAuth === "iam") {
          formikProps.setFieldValue(
            "custom_config.AWS_BEARER_TOKEN_BEDROCK",
            ""
          );
          formikProps.setFieldValue("custom_config.AWS_ACCESS_KEY_ID", "");
          formikProps.setFieldValue("custom_config.AWS_SECRET_ACCESS_KEY", "");
          shouldReset = true;
        }

        if (isEmpty(values?.custom_config?.AWS_REGION_NAME)) {
          shouldReset = true;
        }
        break;
      }
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
    (formikProps.values as any).custom_config?.BEDROCK_AUTH_METHOD,
    (formikProps.values as any).custom_config,
  ]);

  return null;
};

export default LLMFormikEffects;
