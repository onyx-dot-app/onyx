"use client";
import {
  ConnectorIndexingStatus,
  OAuthSlackCallbackResponse,
  DocumentBoostStatus,
  Tag,
  UserGroup,
  ConnectorStatus,
  CCPairBasicInfo,
} from "@/lib/types";
import useSWR, { mutate, useSWRConfig } from "swr";
import { errorHandlingFetcher } from "./fetcher";
import { useContext, useEffect, useState } from "react";
import { DateRangePickerValue } from "@/app/ee/admin/performance/DateRangeSelector";
import { SourceMetadata } from "./search/interfaces";
import { destructureValue, structureValue } from "./llm/utils";
import { ChatSession } from "@/app/chat/interfaces";
import { AllUsersResponse } from "./types";
import { Credential } from "./connectors/credentials";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { PersonaCategory } from "@/app/admin/assistants/interfaces";
import {
  LLMProvider,
  LLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";
import { isAnthropic } from "@/app/admin/configuration/llm/interfaces";

const CREDENTIAL_URL = "/api/manage/admin/credential";

export const usePublicCredentials = () => {
  const { mutate } = useSWRConfig();
  const swrResponse = useSWR<Credential<any>[]>(
    CREDENTIAL_URL,
    errorHandlingFetcher
  );

  return {
    ...swrResponse,
    refreshCredentials: () => mutate(CREDENTIAL_URL),
  };
};

const buildReactedDocsUrl = (ascending: boolean, limit: number) => {
  return `/api/manage/admin/doc-boosts?ascending=${ascending}&limit=${limit}`;
};

export const useMostReactedToDocuments = (
  ascending: boolean,
  limit: number
) => {
  const url = buildReactedDocsUrl(ascending, limit);
  const swrResponse = useSWR<DocumentBoostStatus[]>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshDocs: () => mutate(url),
  };
};

export const useObjectState = <T>(
  initialValue: T
): [T, (update: Partial<T>) => void] => {
  const [state, setState] = useState<T>(initialValue);
  const set = (update: Partial<T>) => {
    setState((prevState) => {
      return {
        ...prevState,
        ...update,
      };
    });
  };
  return [state, set];
};

const INDEXING_STATUS_URL = "/api/manage/admin/connector/indexing-status";
const CONNECTOR_STATUS_URL = "/api/manage/admin/connector/status";

export const useConnectorCredentialIndexingStatus = (
  refreshInterval = 30000, // 30 seconds
  getEditable = false
) => {
  const { mutate } = useSWRConfig();
  const url = `${INDEXING_STATUS_URL}${
    getEditable ? "?get_editable=true" : ""
  }`;
  const swrResponse = useSWR<ConnectorIndexingStatus<any, any>[]>(
    url,
    errorHandlingFetcher,
    { refreshInterval: refreshInterval }
  );

  return {
    ...swrResponse,
    refreshIndexingStatus: () => mutate(url),
  };
};

export const useConnectorStatus = (refreshInterval = 30000) => {
  const { mutate } = useSWRConfig();
  const url = CONNECTOR_STATUS_URL;
  const swrResponse = useSWR<ConnectorStatus<any, any>[]>(
    url,
    errorHandlingFetcher,
    { refreshInterval: refreshInterval }
  );

  return {
    ...swrResponse,
    refreshIndexingStatus: () => mutate(url),
  };
};

export const useBasicConnectorStatus = () => {
  const url = "/api/manage/admin/connector-status";
  const swrResponse = useSWR<CCPairBasicInfo[]>(url, errorHandlingFetcher);
  return {
    ...swrResponse,
    refreshIndexingStatus: () => mutate(url),
  };
};

export const useCategories = () => {
  const { mutate } = useSWRConfig();
  const swrResponse = useSWR<PersonaCategory[]>(
    "/api/persona/categories",
    errorHandlingFetcher
  );

  return {
    ...swrResponse,
    refreshCategories: () => mutate("/api/persona/categories"),
  };
};

export const useTimeRange = (initialValue?: DateRangePickerValue) => {
  return useState<DateRangePickerValue | null>(null);
};

export interface FilterManager {
  timeRange: DateRangePickerValue | null;
  setTimeRange: React.Dispatch<
    React.SetStateAction<DateRangePickerValue | null>
  >;
  selectedSources: SourceMetadata[];
  setSelectedSources: React.Dispatch<React.SetStateAction<SourceMetadata[]>>;
  selectedDocumentSets: string[];
  setSelectedDocumentSets: React.Dispatch<React.SetStateAction<string[]>>;
  selectedTags: Tag[];
  setSelectedTags: React.Dispatch<React.SetStateAction<Tag[]>>;
}

export function useFilters(): FilterManager {
  const [timeRange, setTimeRange] = useTimeRange();
  const [selectedSources, setSelectedSources] = useState<SourceMetadata[]>([]);
  const [selectedDocumentSets, setSelectedDocumentSets] = useState<string[]>(
    []
  );
  const [selectedTags, setSelectedTags] = useState<Tag[]>([]);

  return {
    timeRange,
    setTimeRange,
    selectedSources,
    setSelectedSources,
    selectedDocumentSets,
    setSelectedDocumentSets,
    selectedTags,
    setSelectedTags,
  };
}

export const useUsers = () => {
  const url = "/api/manage/users";

  const swrResponse = useSWR<AllUsersResponse>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshIndexingStatus: () => mutate(url),
  };
};

export interface LlmOverride {
  name: string;
  provider: string;
  modelName: string;
}

export interface LlmOverrideManager {
  llmOverride: LlmOverride;
  updateLLMOverride: (newOverride: LlmOverride) => void;
  globalDefault: LlmOverride;
  setGlobalDefault: React.Dispatch<React.SetStateAction<LlmOverride>>;
  temperature: number | null;
  updateTemperature: (temperature: number | null) => void;
  updateModelOverrideForChatSession: (chatSession?: ChatSession) => void;
}
export function useLlmOverride(
  llmProviders: LLMProviderDescriptor[],
  globalModel?: string | null,
  currentChatSession?: ChatSession,
  defaultTemperature?: number
): LlmOverrideManager {
  const getValidLlmOverride = (
    overrideModel: string | null | undefined
  ): LlmOverride => {
    if (overrideModel) {
      const model = destructureValue(overrideModel);
      const provider = llmProviders.find(
        (p) =>
          p.model_names.includes(model.modelName) &&
          p.provider === model.provider
      );
      if (provider) {
        return { ...model, name: provider.name };
      }
    }
    return { name: "", provider: "", modelName: "" };
  };

  const [globalDefault, setGlobalDefault] = useState<LlmOverride>(
    getValidLlmOverride(globalModel)
  );
  const updateLLMOverride = (newOverride: LlmOverride) => {
    setLlmOverride(
      getValidLlmOverride(
        structureValue(
          newOverride.name,
          newOverride.provider,
          newOverride.modelName
        )
      )
    );
  };

  const [llmOverride, setLlmOverride] = useState<LlmOverride>(
    currentChatSession && currentChatSession.current_alternate_model
      ? getValidLlmOverride(currentChatSession.current_alternate_model)
      : { name: "", provider: "", modelName: "" }
  );

  const updateModelOverrideForChatSession = (chatSession?: ChatSession) => {
    setLlmOverride(
      chatSession && chatSession.current_alternate_model
        ? getValidLlmOverride(chatSession.current_alternate_model)
        : globalDefault
    );
  };

  const [temperature, setTemperature] = useState<number | null>(
    defaultTemperature !== undefined ? defaultTemperature : 0
  );

  useEffect(() => {
    setGlobalDefault(getValidLlmOverride(globalModel));
  }, [globalModel, llmProviders]);

  useEffect(() => {
    setTemperature(defaultTemperature !== undefined ? defaultTemperature : 0);
  }, [defaultTemperature]);

  useEffect(() => {
    if (isAnthropic(llmOverride.provider, llmOverride.modelName)) {
      setTemperature((prevTemp) => Math.min(prevTemp ?? 0, 1.0));
    }
  }, [llmOverride]);

  const updateTemperature = (temperature: number | null) => {
    if (isAnthropic(llmOverride.provider, llmOverride.modelName)) {
      setTemperature((prevTemp) => Math.min(temperature ?? 0, 1.0));
    } else {
      setTemperature(temperature);
    }
  };

  return {
    updateModelOverrideForChatSession,
    llmOverride,
    updateLLMOverride,
    globalDefault,
    setGlobalDefault,
    temperature,
    updateTemperature,
  };
}

/* 
EE Only APIs
*/

const USER_GROUP_URL = "/api/manage/admin/user-group";

export const useUserGroups = (): {
  data: UserGroup[] | undefined;
  isLoading: boolean;
  error: string;
  refreshUserGroups: () => void;
} => {
  const combinedSettings = useContext(SettingsContext);
  const isPaidEnterpriseFeaturesEnabled =
    combinedSettings && combinedSettings.enterpriseSettings !== null;

  const swrResponse = useSWR<UserGroup[]>(
    isPaidEnterpriseFeaturesEnabled ? USER_GROUP_URL : null,
    errorHandlingFetcher
  );

  if (!isPaidEnterpriseFeaturesEnabled) {
    return {
      ...{
        data: [],
        isLoading: false,
        error: "",
      },
      refreshUserGroups: () => {},
    };
  }

  return {
    ...swrResponse,
    refreshUserGroups: () => mutate(USER_GROUP_URL),
  };
};

const MODEL_DISPLAY_NAMES: { [key: string]: string } = {
  // OpenAI models
  "o1-mini": "O1 Mini",
  "o1-preview": "O1 Preview",
  "o1-2024-12-17": "O1",
  "gpt-4": "GPT 4",
  "gpt-4o": "GPT 4o",
  "gpt-4o-2024-08-06": "GPT 4o (Structured Outputs)",
  "gpt-4o-mini": "GPT 4o Mini",
  "gpt-4-0314": "GPT 4 (March 2023)",
  "gpt-4-0613": "GPT 4 (June 2023)",
  "gpt-4-32k-0314": "GPT 4 32k (March 2023)",
  "gpt-4-turbo": "GPT 4 Turbo",
  "gpt-4-turbo-preview": "GPT 4 Turbo (Preview)",
  "gpt-4-1106-preview": "GPT 4 Turbo (November 2023)",
  "gpt-4-vision-preview": "GPT 4 Vision (Preview)",
  "gpt-3.5-turbo": "GPT 3.5 Turbo",
  "gpt-3.5-turbo-0125": "GPT 3.5 Turbo (January 2024)",
  "gpt-3.5-turbo-1106": "GPT 3.5 Turbo (November 2023)",
  "gpt-3.5-turbo-16k": "GPT 3.5 Turbo 16k",
  "gpt-3.5-turbo-0613": "GPT 3.5 Turbo (June 2023)",
  "gpt-3.5-turbo-16k-0613": "GPT 3.5 Turbo 16k (June 2023)",
  "gpt-3.5-turbo-0301": "GPT 3.5 Turbo (March 2023)",

  // Amazon models
  "amazon.nova-micro@v1": "Amazon Nova Micro",
  "amazon.nova-lite@v1": "Amazon Nova Lite",
  "amazon.nova-pro@v1": "Amazon Nova Pro",

  // Meta models
  "llama-3.2-90b-vision-instruct": "Llama 3.2 90B",
  "llama-3.2-11b-vision-instruct": "Llama 3.2 11B",
  "llama-3.3-70b-instruct": "Llama 3.3 70B",

  // Microsoft models
  "phi-3.5-mini-instruct": "Phi 3.5 Mini",
  "phi-3.5-moe-instruct": "Phi 3.5 MoE",
  "phi-3.5-vision-instruct": "Phi 3.5 Vision",

  // Anthropic models
  "claude-3-opus-20240229": "Claude 3 Opus",
  "claude-3-sonnet-20240229": "Claude 3 Sonnet",
  "claude-3-haiku-20240307": "Claude 3 Haiku",
  "claude-2.1": "Claude 2.1",
  "claude-2.0": "Claude 2.0",
  "claude-instant-1.2": "Claude Instant 1.2",
  "claude-3-5-sonnet-20240620": "Claude 3.5 Sonnet",
  "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet (New)",
  "claude-3-5-sonnet-v2@20241022": "Claude 3.5 Sonnet (New)",
  "claude-3.5-sonnet-v2@20241022": "Claude 3.5 Sonnet (New)",
  "claude-3-5-haiku-20241022": "Claude 3.5 Haiku",
  "claude-3-5-haiku@20241022": "Claude 3.5 Haiku",
  "claude-3.5-haiku@20241022": "Claude 3.5 Haiku",

  // Google Models
  "gemini-1.5-pro": "Gemini 1.5 Pro",
  "gemini-1.5-flash": "Gemini 1.5 Flash",
  "gemini-1.5-pro-001": "Gemini 1.5 Pro",
  "gemini-1.5-flash-001": "Gemini 1.5 Flash",
  "gemini-1.5-pro-002": "Gemini 1.5 Pro (v2)",
  "gemini-1.5-flash-002": "Gemini 1.5 Flash (v2)",
  "gemini-2.0-flash-exp": "Gemini 2.0 Flash (Experimental)",

  // Mistral Models
  "mistral-large-2411": "Mistral Large 24.11",
  "mistral-large@2411": "Mistral Large 24.11",

  // Bedrock models
  "meta.llama3-1-70b-instruct-v1:0": "Llama 3.1 70B",
  "meta.llama3-1-8b-instruct-v1:0": "Llama 3.1 8B",
  "meta.llama3-70b-instruct-v1:0": "Llama 3 70B",
  "meta.llama3-2-1b-instruct-v1:0": "Llama 3.2 1B",
  "meta.llama3-2-3b-instruct-v1:0": "Llama 3.2 3B",
  "meta.llama3-2-11b-instruct-v1:0": "Llama 3.2 11B",
  "meta.llama3-2-90b-instruct-v1:0": "Llama 3.2 90B",
  "meta.llama3-8b-instruct-v1:0": "Llama 3 8B",
  "meta.llama2-70b-chat-v1": "Llama 2 70B",
  "meta.llama2-13b-chat-v1": "Llama 2 13B",
  "cohere.command-r-v1:0": "Command R",
  "cohere.command-r-plus-v1:0": "Command R Plus",
  "cohere.command-light-text-v14": "Command Light Text",
  "cohere.command-text-v14": "Command Text",
  "anthropic.claude-instant-v1": "Claude Instant",
  "anthropic.claude-v2:1": "Claude v2.1",
  "anthropic.claude-v2": "Claude v2",
  "anthropic.claude-v1": "Claude v1",
  "anthropic.claude-3-opus-20240229-v1:0": "Claude 3 Opus",
  "anthropic.claude-3-haiku-20240307-v1:0": "Claude 3 Haiku",
  "anthropic.claude-3-5-sonnet-20240620-v1:0": "Claude 3.5 Sonnet",
  "anthropic.claude-3-5-sonnet-20241022-v2:0": "Claude 3.5 Sonnet (New)",
  "anthropic.claude-3-sonnet-20240229-v1:0": "Claude 3 Sonnet",
  "mistral.mistral-large-2402-v1:0": "Mistral Large",
  "mistral.mixtral-8x7b-instruct-v0:1": "Mixtral 8x7B Instruct",
  "mistral.mistral-7b-instruct-v0:2": "Mistral 7B Instruct",
  "amazon.titan-text-express-v1": "Titan Text Express",
  "amazon.titan-text-lite-v1": "Titan Text Lite",
  "ai21.jamba-instruct-v1:0": "Jamba Instruct",
  "ai21.j2-ultra-v1": "J2 Ultra",
  "ai21.j2-mid-v1": "J2 Mid",
};

export function getDisplayNameForModel(modelName: string): string {
  return MODEL_DISPLAY_NAMES[modelName] || modelName;
}

export const defaultModelsByProvider: { [name: string]: string[] } = {
  openai: ["gpt-4", "gpt-4o", "gpt-4o-mini", "o1-mini", "o1-preview"],
  bedrock: [
    "meta.llama3-1-70b-instruct-v1:0",
    "meta.llama3-1-8b-instruct-v1:0",
    "anthropic.claude-3-opus-20240229-v1:0",
    "mistral.mistral-large-2402-v1:0",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
  ],
  anthropic: ["claude-3-opus-20240229", "claude-3-5-sonnet-20241022"],
};
