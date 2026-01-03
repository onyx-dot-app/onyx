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
import { useLLMProviders } from "./hooks/useLLMProviders";

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

  function getFilterString() {
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
  }

  function clearFilters() {
    setTimeRange(null);
    setSelectedSources([]);
    setSelectedDocumentSets([]);
    setSelectedTags([]);
  }

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
  llmProviders: LLMProviderDescriptor[] | undefined;
  isLoadingProviders: boolean;
  hasAnyProvider: boolean;
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

function getDefaultLlmDescriptor(
  llmProviders: LLMProviderDescriptor[]
): LlmDescriptor | null {
  const defaultProvider = llmProviders.find(
    (provider) => provider.is_default_provider
  );
  if (defaultProvider) {
    return {
      name: defaultProvider.name,
      provider: defaultProvider.provider,
      modelName: defaultProvider.default_model_name,
    };
  }
  const firstLlmProvider = llmProviders.find(
    (provider) => provider.model_configurations.length > 0
  );
  if (firstLlmProvider) {
    return {
      name: firstLlmProvider.name,
      provider: firstLlmProvider.provider,
      modelName: firstLlmProvider.default_model_name,
    };
  }
  return null;
}

export function useLlmManager(
  currentChatSession?: ChatSession,
  liveAssistant?: MinimalPersonaSnapshot
): LlmManager {
  const { user } = useUser();

  // Get all user-accessible providers via SWR (general providers - no persona filter)
  // This includes public + all restricted providers user can access via groups
  const { llmProviders: allUserProviders, isLoading: isLoadingAllProviders } =
    useLLMProviders();
  // Fetch persona-specific providers to enforce RBAC restrictions per assistant
  // Only fetch if we have an assistant selected
  const personaId =
    liveAssistant?.id !== undefined ? liveAssistant.id : undefined;
  const {
    llmProviders: personaProviders,
    isLoading: isLoadingPersonaProviders,
  } = useLLMProviders(personaId);

  const llmProviders =
    personaProviders !== undefined ? personaProviders : allUserProviders;

  const [userHasManuallyOverriddenLLM, setUserHasManuallyOverriddenLLM] =
    useState(false);
  const [chatSession, setChatSession] = useState<ChatSession | null>(null);
  const [currentLlm, setCurrentLlm] = useState<LlmDescriptor>({
    name: "",
    provider: "",
    modelName: "",
  });

  // Track the previous assistant ID to detect when it changes
  const prevAssistantIdRef = useRef<number | undefined>(undefined);

  // Reset manual override when switching to a different assistant
  useEffect(() => {
    if (
      liveAssistant?.id !== undefined &&
      prevAssistantIdRef.current !== undefined &&
      liveAssistant.id !== prevAssistantIdRef.current
    ) {
      // User switched to a different assistant - reset manual override
      setUserHasManuallyOverriddenLLM(false);
    }
    prevAssistantIdRef.current = liveAssistant?.id;
  }, [liveAssistant?.id]);

  const llmUpdate = () => {
    /* Should be called when the live assistant or current chat session changes */

    // Don't update if providers haven't loaded yet (undefined/null)
    // Empty arrays are valid (user has no provider access for this assistant)
    if (llmProviders === undefined || llmProviders === null) {
      return;
    }

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
        const defaultLlm = getDefaultLlmDescriptor(llmProviders);
        if (defaultLlm) {
          setCurrentLlm(defaultLlm);
        }
      }
    };

    _llmUpdate();
    setChatSession(currentChatSession || null);
  };

  function getValidLlmDescriptor(
    modelName: string | null | undefined
  ): LlmDescriptor {
    // Return early if providers haven't loaded yet (undefined/null)
    // Empty arrays are valid (user has no provider access for this assistant)
    if (llmProviders === undefined || llmProviders === null) {
      return { name: "", provider: "", modelName: "" };
    }

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

    // Model not found in available providers - fall back to default model
    return (
      getDefaultLlmDescriptor(llmProviders) ?? {
        name: "",
        provider: "",
        modelName: "",
      }
    );
  }

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

  // Track if any provider exists (for onboarding checks)
  const hasAnyProvider = (allUserProviders?.length ?? 0) > 0;

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
    llmProviders,
    isLoadingProviders:
      isLoadingAllProviders ||
      (personaId !== undefined && isLoadingPersonaProviders),
    hasAnyProvider,
  };
}

export function useAuthType(): AuthType | null {
  const { data, error } = useSWR<{ auth_type: AuthType }>(
    "/api/auth/type",
    errorHandlingFetcher
  );

  if (NEXT_PUBLIC_CLOUD_ENABLED) {
    return AuthType.CLOUD;
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
