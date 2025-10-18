"use client";

import {
  DocumentBoostStatus,
  Tag,
  UserGroup,
  ConnectorStatus,
  CCPairBasicInfo,
  FederatedConnectorDetail,
  ValidSources,
  ConnectorIndexingStatusLiteResponse,
  IndexingStatusRequest,
} from "@/lib/types";
import useSWR, { mutate, useSWRConfig } from "swr";
import { errorHandlingFetcher } from "./fetcher";
import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { SourceMetadata } from "./search/interfaces";
import { parseLlmDescriptor } from "./llm/utils";
import { ChatSession } from "@/app/chat/interfaces";
import { AllUsersResponse } from "./types";
import { Credential } from "./connectors/credentials";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import {
  MinimalPersonaSnapshot,
  PersonaLabel,
} from "@/app/admin/assistants/interfaces";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { isAnthropic } from "@/app/admin/configuration/llm/utils";
import { getSourceMetadataForSources } from "./sources";
import { AuthType, NEXT_PUBLIC_CLOUD_ENABLED } from "./constants";
import { useUser } from "@/components/user/UserProvider";
import { SEARCH_TOOL_ID } from "@/app/chat/components/tools/constants";
import { updateTemperatureOverrideForChatSession } from "@/app/chat/services/lib";

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

export const useConnectorIndexingStatusWithPagination = (
  filters: Omit<IndexingStatusRequest, "source" | "source_to_page"> = {},
  refreshInterval = 30000
) => {
  const { mutate } = useSWRConfig();
  //maintains the current page for each source
  const [sourcePages, setSourcePages] = useState<Record<ValidSources, number>>(
    {} as Record<ValidSources, number>
  );
  const [mergedData, setMergedData] = useState<
    ConnectorIndexingStatusLiteResponse[]
  >([]);
  //maintains the loading state for each source
  const [sourceLoadingStates, setSourceLoadingStates] = useState<
    Record<ValidSources, boolean>
  >({} as Record<ValidSources, boolean>);

  //ref to maintain the current source pages for the main request
  const sourcePagesRef = useRef(sourcePages);
  sourcePagesRef.current = sourcePages;

  // Main request that includes current pagination state
  const mainRequest: IndexingStatusRequest = useMemo(
    () => ({
      secondary_index: false,
      access_type_filters: [],
      last_status_filters: [],
      docs_count_operator: null,
      docs_count_value: null,
      ...filters,
    }),
    [filters]
  );

  const swrKey = [INDEXING_STATUS_URL, JSON.stringify(mainRequest)];

  // Main data fetch with auto-refresh
  const { data, isLoading, error } = useSWR<
    ConnectorIndexingStatusLiteResponse[]
  >(
    swrKey,
    () => fetchConnectorIndexingStatus(mainRequest, sourcePagesRef.current),
    {
      refreshInterval,
    }
  );

  // Update merged data when main data changes
  useEffect(() => {
    if (data) {
      setMergedData(data);
    }
  }, [data]);

  // Function to handle page changes for a specific source
  const handlePageChange = useCallback(
    async (source: ValidSources, page: number) => {
      // Update the source page state
      setSourcePages((prev) => ({ ...prev, [source]: page }));

      const sourceRequest: IndexingStatusRequest = {
        ...filters,
        source: source,
        source_to_page: { [source]: page } as Record<ValidSources, number>,
      };
      setSourceLoadingStates((prev) => ({ ...prev, [source]: true }));

      try {
        const sourceData = await fetchConnectorIndexingStatus(sourceRequest);
        if (sourceData && sourceData.length > 0) {
          setMergedData((prevData) =>
            prevData
              .map((existingSource) =>
                existingSource.source === source
                  ? sourceData[0]
                  : existingSource
              )
              .filter(
                (item): item is ConnectorIndexingStatusLiteResponse =>
                  item !== undefined
              )
          );
        }
      } catch (error) {
        console.error(
          `Failed to fetch page ${page} for source ${source}:`,
          error
        );
      } finally {
        setSourceLoadingStates((prev) => ({ ...prev, [source]: false }));
      }
    },
    [filters]
  );

  // Function to refresh all data (maintains current pagination)
  const refreshAllData = useCallback(() => {
    mutate(swrKey);
  }, [mutate, swrKey]);

  // Reset pagination when filters change (but not search)
  const resetPagination = useCallback(() => {
    setSourcePages({} as Record<ValidSources, number>);
  }, []);

  return {
    data: mergedData,
    isLoading,
    error,
    handlePageChange,
    sourcePages,
    sourceLoadingStates,
    refreshAllData,
    resetPagination,
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
  const url = "/api/manage/connector-status";
  const swrResponse = useSWR<CCPairBasicInfo[]>(url, errorHandlingFetcher);
  return {
    ...swrResponse,
    refreshIndexingStatus: () => mutate(url),
  };
};

export const useFederatedConnectors = () => {
  const { mutate } = useSWRConfig();
  const url = "/api/federated";
  const swrResponse = useSWR<FederatedConnectorDetail[]>(
    url,
    errorHandlingFetcher
  );

  return {
    ...swrResponse,
    refreshFederatedConnectors: () => mutate(url),
  };
};

export const useLabels = () => {
  const { mutate } = useSWRConfig();
  const { data: labels, error } = useSWR<PersonaLabel[]>(
    "/api/persona/labels",
    errorHandlingFetcher
  );

  const refreshLabels = async () => {
    return mutate("/api/persona/labels");
  };

  const createLabel = async (name: string) => {
    const response = await fetch("/api/persona/labels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });

    if (response.ok) {
      const newLabel = await response.json();
      mutate("/api/persona/labels", [...(labels || []), newLabel], false);
    }

    return response;
  };

  const updateLabel = async (id: number, name: string) => {
    const response = await fetch(`/api/admin/persona/label/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label_name: name }),
    });

    if (response.ok) {
      mutate(
        "/api/persona/labels",
        labels?.map((label) => (label.id === id ? { ...label, name } : label)),
        false
      );
    }

    return response;
  };

  const deleteLabel = async (id: number) => {
    const response = await fetch(`/api/admin/persona/label/${id}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
    });

    if (response.ok) {
      mutate(
        "/api/persona/labels",
        labels?.filter((label) => label.id !== id),
        false
      );
    }

    return response;
  };

  return {
    labels,
    error,
    refreshLabels,
    createLabel,
    updateLabel,
    deleteLabel,
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
  getFilterString: () => string;
  buildFiltersFromQueryString: (
    filterString: string,
    availableSources: SourceMetadata[],
    availableDocumentSets: string[],
    availableTags: Tag[]
  ) => void;
  clearFilters: () => void;
}

export function useFilters(): FilterManager {
  const [timeRange, setTimeRange] = useTimeRange();
  const [selectedSources, setSelectedSources] = useState<SourceMetadata[]>([]);
  const [selectedDocumentSets, setSelectedDocumentSets] = useState<string[]>(
    []
  );
  const [selectedTags, setSelectedTags] = useState<Tag[]>([]);

  const getFilterString = useCallback(() => {
    const params = new URLSearchParams();

    if (timeRange) {
      params.set("from", timeRange.from.toISOString());
      params.set("to", timeRange.to.toISOString());
    }

    if (selectedSources.length > 0) {
      const sourcesParam = selectedSources
        .map((source) => encodeURIComponent(source.internalName))
        .join(",");
      params.set("sources", sourcesParam);
    }

    if (selectedDocumentSets.length > 0) {
      const docSetsParam = selectedDocumentSets
        .map((ds) => encodeURIComponent(ds))
        .join(",");
      params.set("documentSets", docSetsParam);
    }

    if (selectedTags.length > 0) {
      const tagsParam = selectedTags
        .map((tag) => encodeURIComponent(tag.tag_value))
        .join(",");
      params.set("tags", tagsParam);
    }

    const queryString = params.toString();
    return queryString ? `&${queryString}` : "";
  }, [timeRange, selectedSources, selectedDocumentSets, selectedTags]);

  const clearFilters = useCallback(() => {
    setTimeRange(null);
    setSelectedSources([]);
    setSelectedDocumentSets([]);
    setSelectedTags([]);
  }, []);

  function buildFiltersFromQueryString(
    filterString: string,
    availableSources: SourceMetadata[],
    availableDocumentSets: string[],
    availableTags: Tag[]
  ): void {
    const params = new URLSearchParams(filterString);

    // Parse the "from" parameter as a DateRangePickerValue
    let newTimeRange: DateRangePickerValue | null = null;
    const fromParam = params.get("from");
    const toParam = params.get("to");
    if (fromParam && toParam) {
      const fromDate = new Date(fromParam);
      const toDate = new Date(toParam);
      if (!isNaN(fromDate.getTime()) && !isNaN(toDate.getTime())) {
        newTimeRange = { from: fromDate, to: toDate, selectValue: "" };
      }
    }

    // Parse sources
    let newSelectedSources: SourceMetadata[] = [];
    const sourcesParam = params.get("sources");
    if (sourcesParam) {
      const sourceNames = sourcesParam.split(",").map(decodeURIComponent);
      newSelectedSources = availableSources.filter((source) =>
        sourceNames.includes(source.internalName)
      );
    }

    // Parse document sets
    let newSelectedDocSets: string[] = [];
    const docSetsParam = params.get("documentSets");
    if (docSetsParam) {
      const docSetNames = docSetsParam.split(",").map(decodeURIComponent);
      newSelectedDocSets = availableDocumentSets.filter((ds) =>
        docSetNames.includes(ds)
      );
    }

    // Parse tags
    let newSelectedTags: Tag[] = [];
    const tagsParam = params.get("tags");
    if (tagsParam) {
      const tagValues = tagsParam.split(",").map(decodeURIComponent);
      newSelectedTags = availableTags.filter((tag) =>
        tagValues.includes(tag.tag_value)
      );
    }

    // Update filter manager's values instead of returning
    setTimeRange(newTimeRange);
    setSelectedSources(newSelectedSources);
    setSelectedDocumentSets(newSelectedDocSets);
    setSelectedTags(newSelectedTags);
  }

  return {
    clearFilters,
    timeRange,
    setTimeRange,
    selectedSources,
    setSelectedSources,
    selectedDocumentSets,
    setSelectedDocumentSets,
    selectedTags,
    setSelectedTags,
    getFilterString,
    buildFiltersFromQueryString,
  };
}

interface UseUsersParams {
  includeApiKeys: boolean;
}

export const useUsers = ({ includeApiKeys }: UseUsersParams) => {
  const url = `/api/manage/users?include_api_keys=${includeApiKeys}`;

  const swrResponse = useSWR<AllUsersResponse>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshIndexingStatus: () => mutate(url),
  };
};

export interface LlmDescriptor {
  name: string;
  provider: string;
  modelName: string;
}

export interface LlmManager {
  currentLlm: LlmDescriptor;
  updateCurrentLlm: (newOverride: LlmDescriptor) => void;
  temperature: number;
  updateTemperature: (temperature: number) => void;
  updateModelOverrideBasedOnChatSession: (chatSession?: ChatSession) => void;
  imageFilesPresent: boolean;
  updateImageFilesPresent: (present: boolean) => void;
  liveAssistant: MinimalPersonaSnapshot | null;
  maxTemperature: number;
}

// Things to test
// 1. User override
// 2. User preference (defaults to system wide default if no preference set)
// 3. Current assistant
// 4. Current chat session
// 5. Live assistant

/*
LLM Override is as follows (i.e. this order)
- User override (explicitly set in the chat input bar)
- User preference (defaults to system wide default if no preference set)

On switching to an existing or new chat session or a different assistant:
- If we have a live assistant after any switch with a model override, use that- otherwise use the above hierarchy

Thus, the input should be
- User preference
- LLM Providers (which contain the system wide default)
- Current assistant

Changes take place as
- liveAssistant or currentChatSession changes (and the associated model override is set)
- (updateCurrentLlm) User explicitly setting a model override (and we explicitly override and set the userSpecifiedOverride which we'll use in place of the user preferences unless overridden by an assistant)

If we have a live assistant, we should use that model override

Relevant test: `llm_ordering.spec.ts`.

Temperature override is set as follows:
- For existing chat sessions:
  - If the user has previously overridden the temperature for a specific chat session,
    that value is persisted and used when the user returns to that chat.
  - This persistence applies even if the temperature was set before sending the first message in the chat.
- For new chat sessions:
  - If the search tool is available, the default temperature is set to 0.
  - If the search tool is not available, the default temperature is set to 0.5.

This approach ensures that user preferences are maintained for existing chats while
providing appropriate defaults for new conversations based on the available tools.
*/

export function useLlmManager(
  llmProviders: LLMProviderDescriptor[],
  currentChatSession?: ChatSession,
  liveAssistant?: MinimalPersonaSnapshot
): LlmManager {
  const { user } = useUser();

  const [userHasManuallyOverriddenLLM, setUserHasManuallyOverriddenLLM] =
    useState(false);
  const [chatSession, setChatSession] = useState<ChatSession | null>(null);
  const [currentLlm, setCurrentLlm] = useState<LlmDescriptor>({
    name: "",
    provider: "",
    modelName: "",
  });

  const llmUpdate = () => {
    /* Should be called when the live assistant or current chat session changes */

    // separate function so we can `return` to break out
    const _llmUpdate = () => {
      // if the user has overridden in this session and just switched to a brand
      // new session, use their manually specified model
      if (userHasManuallyOverriddenLLM && !currentChatSession) {
        return;
      }

      if (currentChatSession?.current_alternate_model) {
        setCurrentLlm(
          getValidLlmDescriptor(currentChatSession.current_alternate_model)
        );
      } else if (liveAssistant?.llm_model_version_override) {
        setCurrentLlm(
          getValidLlmDescriptor(liveAssistant.llm_model_version_override)
        );
      } else if (userHasManuallyOverriddenLLM) {
        // if the user has an override and there's nothing special about the
        // current chat session, use the override
        return;
      } else if (user?.preferences?.default_model) {
        setCurrentLlm(getValidLlmDescriptor(user.preferences.default_model));
      } else {
        const defaultProvider = llmProviders.find(
          (provider) => provider.is_default_provider
        );

        if (defaultProvider) {
          setCurrentLlm({
            name: defaultProvider.name,
            provider: defaultProvider.provider,
            modelName: defaultProvider.default_model_name,
          });
        }
      }
    };

    _llmUpdate();
    setChatSession(currentChatSession || null);
  };

  const getValidLlmDescriptor = (
    modelName: string | null | undefined
  ): LlmDescriptor => {
    if (modelName) {
      const model = parseLlmDescriptor(modelName);
      if (!(model.modelName && model.modelName.length > 0)) {
        const provider = llmProviders.find((p) =>
          p.model_configurations
            .map((modelConfiguration) => modelConfiguration.name)
            .includes(modelName)
        );
        if (provider) {
          return {
            modelName: modelName,
            name: provider.name,
            provider: provider.provider,
          };
        }
      }

      const provider = llmProviders.find((p) =>
        p.model_configurations
          .map((modelConfiguration) => modelConfiguration.name)
          .includes(model.modelName)
      );

      if (provider) {
        return { ...model, provider: provider.provider, name: provider.name };
      }
    }
    return { name: "", provider: "", modelName: "" };
  };

  const [imageFilesPresent, setImageFilesPresent] = useState(false);

  const updateImageFilesPresent = (present: boolean) => {
    setImageFilesPresent(present);
  };

  // Manually set the LLM
  const updateCurrentLlm = (newLlm: LlmDescriptor) => {
    setCurrentLlm(newLlm);
    setUserHasManuallyOverriddenLLM(true);
  };

  const updateCurrentLlmToModelName = (modelName: string) => {
    setCurrentLlm(getValidLlmDescriptor(modelName));
    setUserHasManuallyOverriddenLLM(true);
  };

  const updateModelOverrideBasedOnChatSession = (chatSession?: ChatSession) => {
    if (chatSession && chatSession.current_alternate_model?.length > 0) {
      setCurrentLlm(getValidLlmDescriptor(chatSession.current_alternate_model));
    }
  };

  const [temperature, setTemperature] = useState<number>(() => {
    llmUpdate();

    if (currentChatSession?.current_temperature_override != null) {
      return Math.min(
        currentChatSession.current_temperature_override,
        isAnthropic(currentLlm.provider, currentLlm.modelName) ? 1.0 : 2.0
      );
    } else if (
      liveAssistant?.tools.some((tool) => tool.name === SEARCH_TOOL_ID)
    ) {
      return 0;
    }
    return 0.5;
  });

  const maxTemperature = useMemo(() => {
    return isAnthropic(currentLlm.provider, currentLlm.modelName) ? 1.0 : 2.0;
  }, [currentLlm]);

  useEffect(() => {
    if (isAnthropic(currentLlm.provider, currentLlm.modelName)) {
      const newTemperature = Math.min(temperature, 1.0);
      setTemperature(newTemperature);
      if (chatSession?.id) {
        updateTemperatureOverrideForChatSession(chatSession.id, newTemperature);
      }
    }
  }, [currentLlm]);

  useEffect(() => {
    llmUpdate();

    if (!chatSession && currentChatSession) {
      if (temperature) {
        updateTemperatureOverrideForChatSession(
          currentChatSession.id,
          temperature
        );
      }
      return;
    }

    if (currentChatSession?.current_temperature_override) {
      setTemperature(currentChatSession.current_temperature_override);
    } else if (
      liveAssistant?.tools.some((tool) => tool.name === SEARCH_TOOL_ID)
    ) {
      setTemperature(0);
    } else {
      setTemperature(0.5);
    }
  }, [
    liveAssistant,
    currentChatSession,
    llmProviders,
    user?.preferences?.default_model,
  ]);

  const updateTemperature = (temperature: number) => {
    if (isAnthropic(currentLlm.provider, currentLlm.modelName)) {
      setTemperature(Math.min(temperature, 1.0));
    } else {
      setTemperature(temperature);
    }
    if (chatSession) {
      updateTemperatureOverrideForChatSession(chatSession.id, temperature);
    }
  };

  return {
    updateModelOverrideBasedOnChatSession,
    currentLlm,
    updateCurrentLlm,
    temperature,
    updateTemperature,
    imageFilesPresent,
    updateImageFilesPresent,
    liveAssistant: liveAssistant ?? null,
    maxTemperature,
  };
}

export function useAuthType(): AuthType | null {
  const { data, error } = useSWR<{ auth_type: AuthType }>(
    "/api/auth/type",
    errorHandlingFetcher
  );

  if (NEXT_PUBLIC_CLOUD_ENABLED) {
    return "cloud";
  }

  if (error || !data) {
    return null;
  }

  return data.auth_type;
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

export const fetchConnectorIndexingStatus = async (
  request: IndexingStatusRequest = {},
  sourcePages: Record<ValidSources, number> | null = null
): Promise<ConnectorIndexingStatusLiteResponse[]> => {
  const response = await fetch(INDEXING_STATUS_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      secondary_index: false,
      access_type_filters: [],
      last_status_filters: [],
      docs_count_operator: null,
      docs_count_value: null,
      source_to_page: sourcePages || {}, // Use current pagination state
      ...request,
    }),
  });

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  return response.json();
};

const MODEL_DISPLAY_NAMES: { [key: string]: string } = {
  // OpenAI models
  "o1-2025-12-17": "o1 (December 2025)",
  "o3-mini": "o3 Mini",
  "o1-mini": "o1 Mini",
  "o1-preview": "o1 Preview",
  o1: "o1",
  "gpt-5": "GPT 5",
  "gpt-5-mini": "GPT 5 Mini",
  "gpt-4.1": "GPT 4.1",
  "gpt-4": "GPT 4",
  "gpt-4o": "GPT 4o",
  "o4-mini": "o4 Mini",
  o3: "o3",
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
  "phi-4": "Phi 4",

  // Deepseek Models
  "deepseek-r1": "DeepSeek R1",

  // Anthropic models
  "claude-3-opus-20240229": "Claude 3 Opus",
  "claude-3-haiku-20240307": "Claude 3 Haiku",
  "claude-2.0": "Claude 2.0",
  "claude-3-5-sonnet-20240620": "Claude 3.5 Sonnet (June 2024)",
  "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet",
  "claude-3-7-sonnet-20250219": "Claude 3.7 Sonnet",
  "claude-3-5-sonnet-v2@20241022": "Claude 3.5 Sonnet",
  "claude-3.5-sonnet-v2@20241022": "Claude 3.5 Sonnet",
  "claude-3-5-haiku-20241022": "Claude 3.5 Haiku",
  "claude-3-5-haiku@20241022": "Claude 3.5 Haiku",
  "claude-3.5-haiku@20241022": "Claude 3.5 Haiku",
  "claude-3.7-sonnet@202502019": "Claude 3.7 Sonnet",
  "claude-3-7-sonnet-202502019": "Claude 3.7 Sonnet",
  "claude-sonnet-4-5-20250929": "Claude 4.5 Sonnet",
  "claude-haiku-4-5-20251001": "Claude 4.5 Haiku",

  // Google Models

  // 2.5 pro models
  "gemini-2.5-pro": "Gemini 2.5 Pro",
  "gemini-2.5-flash": "Gemini 2.5 Flash",
  "gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite",
  // "gemini-2.5-pro-preview-05-06": "Gemini 2.5 Pro (Preview May 6th)",

  // 2.0 flash lite models
  "gemini-2.0-flash-lite": "Gemini 2.0 Flash Lite",
  "gemini-2.0-flash-lite-001": "Gemini 2.0 Flash Lite (v1)",
  // "gemini-2.0-flash-lite-preview-02-05": "Gemini 2.0 Flash Lite (Prv)",
  // "gemini-2.0-pro-exp-02-05": "Gemini 2.0 Pro (Exp)",

  // 2.0 flash models
  "gemini-2.0-flash": "Gemini 2.0 Flash",
  "gemini-2.0-flash-001": "Gemini 2.0 Flash (v1)",
  "gemini-2.0-flash-exp": "Gemini 2.0 Flash (Experimental)",
  // "gemini-2.5-flash-preview-05-20": "Gemini 2.5 Flash (Preview May 20th)",
  // "gemini-2.0-flash-thinking-exp-01-02":
  //   "Gemini 2.0 Flash Thinking (Experimental January 2nd)",
  // "gemini-2.0-flash-thinking-exp-01-21":
  //   "Gemini 2.0 Flash Thinking (Experimental January 21st)",

  // 1.5 pro models
  "gemini-1.5-pro": "Gemini 1.5 Pro",
  "gemini-1.5-pro-latest": "Gemini 1.5 Pro (Latest)",
  "gemini-1.5-pro-001": "Gemini 1.5 Pro (v1)",
  "gemini-1.5-pro-002": "Gemini 1.5 Pro (v2)",

  // 1.5 flash models
  "gemini-1.5-flash": "Gemini 1.5 Flash",
  "gemini-1.5-flash-002": "Gemini 1.5 Flash (v2)",
  "gemini-1.5-flash-001": "Gemini 1.5 Flash (v1)",

  // Mistral Models
  "mistral-large-2411": "Mistral Large 24.11",
  "mistral-large@2411": "Mistral Large 24.11",
  "ministral-3b": "Ministral 3B",

  // Bedrock models
  "ai21.j2-mid-v1": "J2 Mid",
  "ai21.j2-ultra-v1": "J2 Ultra",
  "ai21.jamba-instruct-v1:0": "Jamba Instruct",
  "amazon.titan-text-express-v1": "Titan Text Express",
  "amazon.titan-text-lite-v1": "Titan Text Lite",
  "anthropic.claude-3-5-sonnet-20240620-v1:0": "Claude 3.5 Sonnet v1",
  "anthropic.claude-3-5-sonnet-20241022-v2:0": "Claude 3.5 Sonnet v2",
  "anthropic.claude-3-haiku-20240307-v1:0": "Claude 3 Haiku",
  "anthropic.claude-3-opus-20240229-v1:0": "Claude 3 Opus",
  "anthropic.claude-3-sonnet-20240229-v1:0": "Claude 3 Sonnet",
  "anthropic.claude-3-7-sonnet-20250219-v1:0": "Claude 3.7 Sonnet",
  "anthropic.claude-haiku-4-5-20251001-v1:0": "Claude 4.5 Haiku",
  "anthropic.claude-instant-v1": "Claude Instant",
  "anthropic.claude-v1": "Claude v1",
  "anthropic.claude-v2:1": "Claude v2.1",
  "cohere.command-light-text-v14": "Command Light Text",
  "cohere.command-r-plus-v1:0": "Command R Plus",
  "cohere.command-r-v1:0": "Command R",
  "cohere.command-text-v14": "Command Text",
  "global.anthropic.claude-sonnet-4-5-20250929-v1:0":
    "Claude 4.5 Sonnet (Global)",
  "global.anthropic.claude-sonnet-4-20250514-v1:0": "Claude 4 Sonnet (Global)",
  "meta.llama2-13b-chat-v1": "Llama 2 13B",
  "meta.llama2-70b-chat-v1": "Llama 2 70B",
  "meta.llama3-1-70b-instruct-v1:0": "Llama 3.1 70B",
  "meta.llama3-1-8b-instruct-v1:0": "Llama 3.1 8B",
  "meta.llama3-2-1b-instruct-v1:0": "Llama 3.2 1B",
  "meta.llama3-2-11b-instruct-v1:0": "Llama 3.2 11B",
  "meta.llama3-2-3b-instruct-v1:0": "Llama 3.2 3B",
  "meta.llama3-2-90b-instruct-v1:0": "Llama 3.2 90B",
  "meta.llama3-70b-instruct-v1:0": "Llama 3 70B",
  "meta.llama3-8b-instruct-v1:0": "Llama 3 8B",
  "mistral.mistral-7b-instruct-v0:2": "Mistral 7B Instruct",
  "mistral.mistral-large-2402-v1:0": "Mistral Large",
  "mistral.mixtral-8x7b-instruct-v0:1": "Mixtral 8x7B Instruct",
  "us.amazon.nova-lite-v1:0": "Nova Lite (US)",
  "us.amazon.nova-micro-v1:0": "Nova Micro (US)",
  "us.amazon.nova-premier-v1:0": "Nova Premier (US)",
  "us.amazon.nova-pro-v1:0": "Nova Pro (US)",
  "us.anthropic.claude-3-5-haiku-20241022-v1:0": "Claude 3.5 Haiku (US)",
  "us.anthropic.claude-3-5-sonnet-20240620-v1:0": "Claude 3.5 Sonnet v1 (US)",
  "us.anthropic.claude-3-5-sonnet-20241022-v2:0": "Claude 3.5 Sonnet v2 (US)",
  "us.anthropic.claude-3-7-sonnet-20250219-v1:0": "Claude 3.7 Sonnet (US)",
  "us.anthropic.claude-3-haiku-20240307-v1:0": "Claude 3 Haiku (US)",
  "us.anthropic.claude-opus-4-1-20250805-v1:0": "Claude Opus 4.1 (US)",
  "us.anthropic.claude-opus-4-20250514-v1:0": "Claude Opus 4 (US)",
  "us.anthropic.claude-sonnet-4-20250514-v1:0": "Claude 4 Sonnet (US)",
  "us.anthropic.claude-sonnet-4-5-20250929-v1:0": "Claude 4.5 Sonnet (US)",
  "us.anthropic.claude-haiku-4-5-20251001-v1:0": "Claude 4.5 Haiku (US)",
  "us.deepseek.r1-v1:0": "DeepSeek R1 (US)",
  "us.meta.llama3-1-405b-instruct-v1:0": "Llama 3.1 405B (US)",
  "us.meta.llama3-1-70b-instruct-v1:0": "Llama 3.1 70B (US)",
  "us.meta.llama3-1-8b-instruct-v1:0": "Llama 3.1 8B (US)",
  "us.meta.llama3-2-1b-instruct-v1:0": "Llama 3.2 1B (US)",
  "us.meta.llama3-2-11b-instruct-v1:0": "Llama 3.2 11B (US)",
  "us.meta.llama3-2-3b-instruct-v1:0": "Llama 3.2 3B (US)",
  "us.meta.llama3-2-90b-instruct-v1:0": "Llama 3.2 90B (US)",
  "us.meta.llama3-3-70b-instruct-v1:0": "Llama 3.3 70B (US)",
  "us.meta.llama4-maverick-17b-instruct-v1:0": "Llama 4 Maverick 17B (US)",
  "us.meta.llama4-scout-17b-instruct-v1:0": "Llama 4 Scout 17B (US)",
  "us.mistral.pixtral-large-2502-v1:0": "Pixtral Large (US)",

  // Ollama cloud models
  "gpt-oss:20b-cloud": "gpt-oss 20B Cloud",
  "gpt-oss:120b-cloud": "gpt-oss 120B Cloud",
  "deepseek-v3.1:671b-cloud": "DeepSeek-v3.1 671B Cloud",
  "kimi-k2:1t": "Kimi K2 1T Cloud",
  "qwen3-coder:480b-cloud": "Qwen3-Coder 480B Cloud",

  // Ollama models in litellm map (disjoint from ollama's supported model list)
  // https://models.litellm.ai --> provider ollama
  codegeex4: "CodeGeeX 4",
  codegemma: "CodeGemma",
  codellama: "CodeLLama",
  "deepseek-coder-v2-base": "DeepSeek-Coder-v2 Base",
  "deepseek-coder-v2-instruct": "DeepSeek-Coder-v2 Instruct",
  "deepseek-coder-v2-lite-base": "DeepSeek-Coder-v2 Lite Base",
  "deepseek-coder-v2-lite-instruct": "DeepSeek-Coder-v2 Lite Instruct",
  "internlm2_5-20b-chat": "InternLM 2.5 20B Chat",
  llama2: "Llama 2",
  "llama2-uncensored": "Llama 2 Uncensored",
  "llama2:13b": "Llama 2 13B",
  "llama2:70b": "Llama 2 70B",
  "llama2:7b": "Llama 2 7B",
  llama3: "Llama 3",
  "llama3:70b": "Llama 3 70B",
  "llama3:8b": "Llama 3 8B",
  mistral: "Mistral", // Mistral 7b
  "mistral-7B-Instruct-v0.1": "Mistral 7B Instruct v0.1",
  "mistral-7B-Instruct-v0.2": "Mistral 7B Instruct v0.2",
  "mistral-large-instruct-2407": "Mistral Large Instruct 24.07",
  "mixtral-8x22B-Instruct-v0.1": "Mixtral 8x22B Instruct v0.1",
  "mixtral8x7B-Instruct-v0.1": "Mixtral 8x7B Instruct v0.1",
  "orca-mini": "Orca Mini",
  vicuna: "Vicuna",
};

export function getDisplayNameForModel(modelName: string): string {
  if (modelName.startsWith("bedrock/")) {
    const parts = modelName.split("/");
    const lastPart = parts[parts.length - 1];
    if (lastPart === undefined) {
      return "";
    }

    const displayName = MODEL_DISPLAY_NAMES[lastPart];
    return displayName || lastPart;
  }

  return MODEL_DISPLAY_NAMES[modelName] || modelName;
}

// Get source metadata for configured sources - deduplicated by source type
function getConfiguredSources(
  availableSources: ValidSources[]
): Array<SourceMetadata & { originalName: string; uniqueKey: string }> {
  const allSources = getSourceMetadataForSources(availableSources);

  const seenSources = new Set<string>();
  const configuredSources: Array<
    SourceMetadata & { originalName: string; uniqueKey: string }
  > = [];

  availableSources.forEach((sourceName) => {
    // Handle federated connectors by removing the federated_ prefix
    const cleanName = sourceName.replace("federated_", "");
    // Skip if we've already seen this source type
    if (seenSources.has(cleanName)) return;
    seenSources.add(cleanName);
    const source = allSources.find(
      (source) => source.internalName === cleanName
    );
    if (source) {
      configuredSources.push({
        ...source,
        originalName: sourceName,
        uniqueKey: cleanName,
      });
    }
  });
  return configuredSources;
}

interface UseSourcePreferencesProps {
  availableSources: ValidSources[];
  selectedSources: SourceMetadata[];
  setSelectedSources: (sources: SourceMetadata[]) => void;
}

const LS_SELECTED_INTERNAL_SEARCH_SOURCES_KEY = "selectedInternalSearchSources";

export function useSourcePreferences({
  availableSources,
  selectedSources,
  setSelectedSources,
}: UseSourcePreferencesProps) {
  const [sourcesInitialized, setSourcesInitialized] = useState(false);

  // Load saved source preferences from localStorage
  const loadSavedSourcePreferences = () => {
    if (typeof window === "undefined") return null;
    const saved = localStorage.getItem(LS_SELECTED_INTERNAL_SEARCH_SOURCES_KEY);
    if (!saved) return null;
    try {
      return JSON.parse(saved);
    } catch {
      return null;
    }
  };

  const persistSourcePreferencesState = (sources: SourceMetadata[]) => {
    if (typeof window === "undefined") return;
    localStorage.setItem(
      LS_SELECTED_INTERNAL_SEARCH_SOURCES_KEY,
      JSON.stringify(sources)
    );
  };

  // Initialize sources - load from localStorage or enable all by default
  useEffect(() => {
    if (!sourcesInitialized && availableSources.length > 0) {
      const savedSources = loadSavedSourcePreferences();
      const availableSourceMetadata = getConfiguredSources(availableSources);

      if (savedSources !== null) {
        // Filter out saved sources that no longer exist
        const validSavedSources = savedSources.filter(
          (savedSource: SourceMetadata) =>
            availableSourceMetadata.some(
              (availableSource) =>
                availableSource.uniqueKey === savedSource.uniqueKey
            )
        );

        // Find new sources that weren't in the saved preferences
        const savedSourceKeys = new Set(
          validSavedSources.map((s: SourceMetadata) => s.uniqueKey)
        );
        const newSources = availableSourceMetadata.filter(
          (availableSource) => !savedSourceKeys.has(availableSource.uniqueKey)
        );

        // Merge valid saved sources with new sources (enable new sources by default)
        const mergedSources = [...validSavedSources, ...newSources];
        setSelectedSources(mergedSources);

        // Persist the merged state if there were any new sources
        if (newSources.length > 0) {
          persistSourcePreferencesState(mergedSources);
        }
      } else {
        // First time user - enable all sources by default
        setSelectedSources(availableSourceMetadata);
      }
      setSourcesInitialized(true);
    }
  }, [availableSources, sourcesInitialized, setSelectedSources]);

  const enableAllSources = () => {
    const allSourceMetadata = getConfiguredSources(availableSources);
    setSelectedSources(allSourceMetadata);
    persistSourcePreferencesState(allSourceMetadata);
  };

  const disableAllSources = () => {
    setSelectedSources([]);
    persistSourcePreferencesState([]);
  };

  const toggleSource = (sourceUniqueKey: string) => {
    const configuredSource = getConfiguredSources(availableSources).find(
      (s) => s.uniqueKey === sourceUniqueKey
    );
    if (!configuredSource) return;

    const isCurrentlySelected = selectedSources.some(
      (s) => s.uniqueKey === configuredSource.uniqueKey
    );

    let newSources: SourceMetadata[];
    if (isCurrentlySelected) {
      newSources = selectedSources.filter(
        (s) => s.uniqueKey !== configuredSource.uniqueKey
      );
    } else {
      newSources = [...selectedSources, configuredSource];
    }

    setSelectedSources(newSources);
    persistSourcePreferencesState(newSources);
  };

  const isSourceEnabled = (sourceUniqueKey: string) => {
    const configuredSource = getConfiguredSources(availableSources).find(
      (s) => s.uniqueKey === sourceUniqueKey
    );
    if (!configuredSource) return false;
    return selectedSources.some(
      (s: SourceMetadata) => s.uniqueKey === configuredSource.uniqueKey
    );
  };

  return {
    sourcesInitialized,
    enableAllSources,
    disableAllSources,
    toggleSource,
    isSourceEnabled,
  };
}
