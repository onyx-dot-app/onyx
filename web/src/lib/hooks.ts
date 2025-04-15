"use client";
import {
  ConnectorIndexingStatus,
  DocumentBoostStatus,
  Tag,
  UserGroup,
  ConnectorStatus,
  CCPairBasicInfo,
  ValidSources,
} from "@/lib/types";
import useSWR, { mutate, useSWRConfig } from "swr";
import { errorHandlingFetcher } from "./fetcher";
import { useContext, useEffect, useMemo, useState } from "react";
import { DateRangePickerValue } from "@/app/ee/admin/performance/DateRangeSelector";
import { Filters, SourceMetadata } from "./search/interfaces";
import {
  destructureValue,
  findProviderForModel,
  structureValue,
} from "./llm/utils";
import { ChatSession } from "@/app/chat/interfaces";
import { AllUsersResponse } from "./types";
import { Credential } from "./connectors/credentials";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { Persona, PersonaLabel } from "@/app/admin/assistants/interfaces";
import {
  isAnthropic,
  LLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";

import { getSourceMetadata } from "./sources";
import { AuthType, NEXT_PUBLIC_CLOUD_ENABLED } from "./constants";
import { useUser } from "@/components/user/UserProvider";
import { SEARCH_TOOL_ID } from "@/app/chat/tools/constants";
import { updateTemperatureOverrideForChatSession } from "@/app/chat/lib";

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
  const url = "/api/manage/connector-status";
  const swrResponse = useSWR<CCPairBasicInfo[]>(url, errorHandlingFetcher);
  return {
    ...swrResponse,
    refreshIndexingStatus: () => mutate(url),
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
    availableSources: ValidSources[],
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

  const getFilterString = () => {
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
  };

  const clearFilters = () => {
    setTimeRange(null);
    setSelectedSources([]);
    setSelectedDocumentSets([]);
    setSelectedTags([]);
  };

  function buildFiltersFromQueryString(
    filterString: string,
    availableSources: ValidSources[],
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
    const availableSourcesMetadata = availableSources.map(getSourceMetadata);
    let newSelectedSources: SourceMetadata[] = [];
    const sourcesParam = params.get("sources");
    if (sourcesParam) {
      const sourceNames = sourcesParam.split(",").map(decodeURIComponent);
      newSelectedSources = availableSourcesMetadata.filter((source) =>
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
  liveAssistant: Persona | null;
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
  liveAssistant?: Persona
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
      const model = destructureValue(modelName);
      if (!(model.modelName && model.modelName.length > 0)) {
        const provider = llmProviders.find((p) =>
          p.model_names.includes(modelName)
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
        p.model_names.includes(model.modelName)
      );

      if (provider) {
        return { ...model, name: provider.name };
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
    const provider =
      newLlm.provider || findProviderForModel(llmProviders, newLlm.modelName);
    const structuredValue = structureValue(
      newLlm.name,
      provider,
      newLlm.modelName
    );
    setCurrentLlm(getValidLlmDescriptor(structuredValue));
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
  }, [liveAssistant, currentChatSession]);

  const updateTemperature = (temperature: number) => {
    if (isAnthropic(currentLlm.provider, currentLlm.modelName)) {
      setTemperature((prevTemp) => Math.min(temperature, 1.0));
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

export function useHumanReadableModelNamesMap(): {
  [key: string]: string;
} | null {
  // Set a very long revalidation time (e.g., 24 hours)
  const { data, error } = useSWR<{ [key: string]: string }>(
    "/api/llm/human_readable_model_names_map",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      refreshInterval: 86400000, // 24 hours in milliseconds
      dedupingInterval: 86400000,
    }
  );

  if (error || !data) {
    return null;
  }

  return data;
}

export function getHumanReadableName(
  humanReadableModelNamesMap: { [key: string]: string } | null,
  modelName: string,
  fallbackModelName: string | null | undefined = undefined
): string {
  let name = modelName;
  if (modelName.startsWith("bedrock")) {
    const [_, last] = name.split("/");
    name = last;
  }

  return (
    (humanReadableModelNamesMap && humanReadableModelNamesMap[name]) ??
    fallbackModelName ??
    name
  );
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

export const defaultModelsByProvider: { [name: string]: string[] } = {
  openai: ["gpt-4", "gpt-4o", "gpt-4o-mini", "o3-mini", "o1-mini", "o1"],
  bedrock: [
    "meta.llama3-1-70b-instruct-v1:0",
    "meta.llama3-1-8b-instruct-v1:0",
    "anthropic.claude-3-opus-20240229-v1:0",
    "mistral.mistral-large-2402-v1:0",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "anthropic.claude-3-7-sonnet-20250219-v1:0",
  ],
  anthropic: ["claude-3-opus-20240229", "claude-3-5-sonnet-20241022"],
};
