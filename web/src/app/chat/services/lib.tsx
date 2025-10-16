import {
  OnyxDocument,
  Filters,
  DocumentInfoPacket,
  StreamStopInfo,
} from "@/lib/search/interfaces";
import { handleSSEStream } from "@/lib/search/streamingUtils";
import { ChatState, FeedbackType } from "@/app/chat/interfaces";
import { MutableRefObject, RefObject, useEffect, useRef } from "react";
import {
  BackendMessage,
  ChatSession,
  DocumentsResponse,
  FileDescriptor,
  FileChatDisplay,
  Message,
  MessageResponseIDInfo,
  ResearchType,
  RetrievalType,
  StreamingError,
  ToolCallMetadata,
  UserKnowledgeFilePacket,
} from "../interfaces";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { ReadonlyURLSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "./searchParams";
import { Settings } from "@/app/admin/settings/interfaces";
import {
  IMAGE_GENERATION_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
} from "@/app/chat/components/tools/constants";
import { SEARCH_TOOL_ID } from "@/app/chat/components/tools/constants";
import { Packet } from "./streamingModels";

// Date range group constants
export const DATE_RANGE_GROUPS = {
  TODAY: "Today",
  PREVIOUS_7_DAYS: "Previous 7 Days",
  PREVIOUS_30_DAYS: "Previous 30 Days",
  OVER_30_DAYS: "Over 30 Days",
} as const;

interface ChatRetentionInfo {
  chatRetentionDays: number;
  daysFromCreation: number;
  daysUntilExpiration: number;
  showRetentionWarning: boolean;
}

export function getChatRetentionInfo(
  chatSession: ChatSession,
  settings: Settings
): ChatRetentionInfo {
  // If `maximum_chat_retention_days` isn't set- never display retention warning.
  const chatRetentionDays = settings.maximum_chat_retention_days || 10000;
  const updatedDate = new Date(chatSession.time_updated);
  const today = new Date();
  const daysFromCreation = Math.ceil(
    (today.getTime() - updatedDate.getTime()) / (1000 * 3600 * 24)
  );
  const daysUntilExpiration = chatRetentionDays - daysFromCreation;
  const showRetentionWarning =
    chatRetentionDays < 7 ? daysUntilExpiration < 2 : daysUntilExpiration < 7;

  return {
    chatRetentionDays,
    daysFromCreation,
    daysUntilExpiration,
    showRetentionWarning,
  };
}

export async function updateLlmOverrideForChatSession(
  chatSessionId: string,
  newAlternateModel: string
) {
  const response = await fetch("/api/chat/update-chat-session-model", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      chat_session_id: chatSessionId,
      new_alternate_model: newAlternateModel,
    }),
  });
  return response;
}

export async function updateTemperatureOverrideForChatSession(
  chatSessionId: string,
  newTemperature: number
) {
  const response = await fetch("/api/chat/update-chat-session-temperature", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      chat_session_id: chatSessionId,
      temperature_override: newTemperature,
    }),
  });
  return response;
}

export async function createChatSession(
  personaId: number,
  description: string | null,
  projectId: number | null
): Promise<string> {
  const createChatSessionResponse = await fetch(
    "/api/chat/create-chat-session",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        persona_id: personaId,
        description,
        project_id: projectId,
      }),
    }
  );
  if (!createChatSessionResponse.ok) {
    console.error(
      `Failed to create chat session - ${createChatSessionResponse.status}`
    );
    throw Error("Failed to create chat session");
  }
  const chatSessionResponseJson = await createChatSessionResponse.json();
  return chatSessionResponseJson.chat_session_id;
}

export const isPacketType = (data: any): data is PacketType => {
  return (
    data.hasOwnProperty("answer_piece") ||
    data.hasOwnProperty("top_documents") ||
    data.hasOwnProperty("tool_name") ||
    data.hasOwnProperty("file_ids") ||
    data.hasOwnProperty("error") ||
    data.hasOwnProperty("message_id") ||
    data.hasOwnProperty("stop_reason") ||
    data.hasOwnProperty("user_message_id") ||
    data.hasOwnProperty("reserved_assistant_message_id")
  );
};

export type PacketType =
  | ToolCallMetadata
  | BackendMessage
  | DocumentInfoPacket
  | DocumentsResponse
  | FileChatDisplay
  | StreamingError
  | MessageResponseIDInfo
  | StreamStopInfo
  | UserKnowledgeFilePacket
  | Packet;

export interface SendMessageParams {
  regenerate: boolean;
  message: string;
  fileDescriptors?: FileDescriptor[];
  parentMessageId: number | null;
  chatSessionId: string;
  filters: Filters | null;
  selectedDocumentIds: number[] | null;
  queryOverride?: string;
  forceSearch?: boolean;
  modelProvider?: string;
  modelVersion?: string;
  temperature?: number;
  systemPromptOverride?: string;
  useExistingUserMessage?: boolean;
  alternateAssistantId?: number;
  signal?: AbortSignal;
  currentMessageFiles?: FileDescriptor[];
  useAgentSearch?: boolean;
  enabledToolIds?: number[];
  forcedToolIds?: number[];
}

export async function* sendMessage({
  regenerate,
  message,
  fileDescriptors,
  currentMessageFiles,
  parentMessageId,
  chatSessionId,
  filters,
  selectedDocumentIds,
  queryOverride,
  forceSearch,
  modelProvider,
  modelVersion,
  temperature,
  systemPromptOverride,
  useExistingUserMessage,
  alternateAssistantId,
  signal,
  useAgentSearch,
  enabledToolIds,
  forcedToolIds,
}: SendMessageParams): AsyncGenerator<PacketType, void, unknown> {
  const documentsAreSelected =
    selectedDocumentIds && selectedDocumentIds.length > 0;
  const payload = {
    alternate_assistant_id: alternateAssistantId,
    chat_session_id: chatSessionId,
    parent_message_id: parentMessageId,
    message: message,
    // just use the default prompt for the assistant.
    // should remove this in the future, as we don't support multiple prompts for a
    // single assistant anyways
    prompt_id: null,
    search_doc_ids: documentsAreSelected ? selectedDocumentIds : null,
    file_descriptors: fileDescriptors,
    current_message_files: currentMessageFiles,
    regenerate,
    retrieval_options: !documentsAreSelected
      ? {
          run_search: queryOverride || forceSearch ? "always" : "auto",
          real_time: true,
          filters: filters,
        }
      : null,
    query_override: queryOverride,
    prompt_override: systemPromptOverride
      ? {
          system_prompt: systemPromptOverride,
        }
      : null,
    llm_override:
      temperature || modelVersion
        ? {
            temperature,
            model_provider: modelProvider,
            model_version: modelVersion,
          }
        : null,
    use_existing_user_message: useExistingUserMessage,
    use_agentic_search: useAgentSearch ?? false,
    allowed_tool_ids: enabledToolIds,
    forced_tool_ids: forcedToolIds,
  };

  const body = JSON.stringify(payload);

  const response = await fetch(`/api/chat/send-message`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body,
    signal,
  });

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  yield* handleSSEStream<PacketType>(response, signal);
}

export async function nameChatSession(chatSessionId: string) {
  const response = await fetch("/api/chat/rename-chat-session", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      chat_session_id: chatSessionId,
      name: null,
    }),
  });
  return response;
}

export async function patchMessageToBeLatest(messageId: number) {
  const response = await fetch("/api/chat/set-message-as-latest", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message_id: messageId,
    }),
  });
  return response;
}

export async function handleChatFeedback(
  messageId: number,
  feedback: FeedbackType,
  feedbackDetails: string,
  predefinedFeedback: string | undefined
) {
  const response = await fetch("/api/chat/create-chat-message-feedback", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      chat_message_id: messageId,
      is_positive: feedback === "like",
      feedback_text: feedbackDetails,
      predefined_feedback: predefinedFeedback,
    }),
  });
  return response;
}

export async function renameChatSession(
  chatSessionId: string,
  newName: string
) {
  const response = await fetch(`/api/chat/rename-chat-session`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      chat_session_id: chatSessionId,
      name: newName,
    }),
  });
  return response;
}

export async function deleteChatSession(chatSessionId: string) {
  const response = await fetch(
    `/api/chat/delete-chat-session/${chatSessionId}`,
    {
      method: "DELETE",
    }
  );
  return response;
}

export async function deleteAllChatSessions() {
  const response = await fetch(`/api/chat/delete-all-chat-sessions`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
  return response;
}

export async function getAvailableContextTokens(
  chatSessionId: string
): Promise<number> {
  const response = await fetch(
    `/api/chat/available-context-tokens/${chatSessionId}`
  );
  if (!response.ok) {
    return 0;
  }
  const data = (await response.json()) as { available_tokens: number };
  return data?.available_tokens ?? 0;
}

export async function* simulateLLMResponse(input: string, delay: number = 30) {
  // Split the input string into tokens. This is a simple example, and in real use case, tokenization can be more complex.
  // Iterate over tokens and yield them one by one
  const tokens = input.match(/.{1,3}|\n/g) || [];

  for (const token of tokens) {
    // In a real-world scenario, there might be a slight delay as tokens are being generated
    await new Promise((resolve) => setTimeout(resolve, delay)); // 40ms delay to simulate response time

    // Yielding each token
    yield token;
  }
}

export function getHumanAndAIMessageFromMessageNumber(
  messageHistory: Message[],
  messageId: number
) {
  let messageInd;
  // -1 is special -> means use the last message
  if (messageId === -1) {
    messageInd = messageHistory.length - 1;
  } else {
    messageInd = messageHistory.findIndex(
      (message) => message.messageId === messageId
    );
  }
  if (messageInd !== -1) {
    const matchingMessage = messageHistory[messageInd];
    const pairedMessage =
      matchingMessage && matchingMessage.type === "user"
        ? messageHistory[messageInd + 1]
        : messageHistory[messageInd - 1];

    const humanMessage =
      matchingMessage && matchingMessage.type === "user"
        ? matchingMessage
        : pairedMessage;
    const aiMessage =
      matchingMessage && matchingMessage.type === "user"
        ? pairedMessage
        : matchingMessage;

    return {
      humanMessage,
      aiMessage,
    };
  } else {
    return {
      humanMessage: null,
      aiMessage: null,
    };
  }
}

export function getCitedDocumentsFromMessage(message: Message) {
  if (!message.citations || !message.documents) {
    return [];
  }

  const documentsWithCitationKey: [string, OnyxDocument][] = [];
  Object.entries(message.citations).forEach(([citationKey, documentDbId]) => {
    const matchingDocument = message.documents!.find(
      (document) => document.db_doc_id === documentDbId
    );
    if (matchingDocument) {
      documentsWithCitationKey.push([citationKey, matchingDocument]);
    }
  });
  return documentsWithCitationKey;
}

export function groupSessionsByDateRange(chatSessions: ChatSession[]) {
  const today = new Date();
  today.setHours(0, 0, 0, 0); // Set to start of today for accurate comparison

  const groups: Record<string, ChatSession[]> = {
    [DATE_RANGE_GROUPS.TODAY]: [],
    [DATE_RANGE_GROUPS.PREVIOUS_7_DAYS]: [],
    [DATE_RANGE_GROUPS.PREVIOUS_30_DAYS]: [],
    [DATE_RANGE_GROUPS.OVER_30_DAYS]: [],
  };

  chatSessions.forEach((chatSession) => {
    const chatSessionDate = new Date(chatSession.time_updated);

    const diffTime = today.getTime() - chatSessionDate.getTime();
    const diffDays = diffTime / (1000 * 3600 * 24); // Convert time difference to days

    if (diffDays < 1) {
      const groups_today = groups[DATE_RANGE_GROUPS.TODAY];
      if (groups_today) {
        groups_today.push(chatSession);
      }
    } else if (diffDays <= 7) {
      const groups_7 = groups[DATE_RANGE_GROUPS.PREVIOUS_7_DAYS];
      if (groups_7) {
        groups_7.push(chatSession);
      }
    } else if (diffDays <= 30) {
      const groups_30 = groups[DATE_RANGE_GROUPS.PREVIOUS_30_DAYS];
      if (groups_30) {
        groups_30.push(chatSession);
      }
    } else {
      const groups_over_30 = groups[DATE_RANGE_GROUPS.OVER_30_DAYS];
      if (groups_over_30) {
        groups_over_30.push(chatSession);
      }
    }
  });

  return groups;
}

export function processRawChatHistory(
  rawMessages: BackendMessage[],
  packets: Packet[][]
): Map<number, Message> {
  const messages: Map<number, Message> = new Map();
  const parentMessageChildrenMap: Map<number, number[]> = new Map();

  let assistantMessageInd = 0;

  rawMessages.forEach((messageInfo, _ind) => {
    const packetsForMessage = packets[assistantMessageInd];
    if (messageInfo.message_type === "assistant") {
      assistantMessageInd++;
    }

    const hasContextDocs =
      (messageInfo?.context_docs?.top_documents || []).length > 0;
    let retrievalType;
    if (hasContextDocs) {
      if (messageInfo.rephrased_query) {
        retrievalType = RetrievalType.Search;
      } else {
        retrievalType = RetrievalType.SelectedDocs;
      }
    } else {
      retrievalType = RetrievalType.None;
    }

    const message: Message = {
      // for existing messages, use the message_id as the nodeId
      // all that matters is that the nodeId is unique for a given chat session
      nodeId: messageInfo.message_id,
      messageId: messageInfo.message_id,
      message: messageInfo.message,
      type: messageInfo.message_type as "user" | "assistant",
      files: messageInfo.files,
      alternateAssistantID:
        messageInfo.alternate_assistant_id !== null
          ? Number(messageInfo.alternate_assistant_id)
          : null,
      // only include these fields if this is an assistant message so that
      // this is identical to what is computed at streaming time
      ...(messageInfo.message_type === "assistant"
        ? {
            retrievalType: retrievalType,
            researchType: messageInfo.research_type as ResearchType | undefined,
            query: messageInfo.rephrased_query,
            documents: messageInfo?.context_docs?.top_documents || [],
            citations: messageInfo?.citations || {},
          }
        : {}),
      toolCall: messageInfo.tool_call,
      parentNodeId: messageInfo.parent_message,
      childrenNodeIds: [],
      latestChildNodeId: messageInfo.latest_child_message,
      overridden_model: messageInfo.overridden_model,
      packets: packetsForMessage || [],
    };

    messages.set(messageInfo.message_id, message);

    if (messageInfo.parent_message !== null) {
      if (!parentMessageChildrenMap.has(messageInfo.parent_message)) {
        parentMessageChildrenMap.set(messageInfo.parent_message, []);
      }
      parentMessageChildrenMap
        .get(messageInfo.parent_message)!
        .push(messageInfo.message_id);
    }
  });

  // Populate childrenMessageIds for each message
  parentMessageChildrenMap.forEach((childrenIds, parentId) => {
    childrenIds.sort((a, b) => a - b);
    const parentMesage = messages.get(parentId);
    if (parentMesage) {
      parentMesage.childrenNodeIds = childrenIds;
    }
  });

  return messages;
}

export function checkAnyAssistantHasSearch(
  messageHistory: Message[],
  availableAssistants: MinimalPersonaSnapshot[],
  livePersona: MinimalPersonaSnapshot
): boolean {
  const response =
    messageHistory.some((message) => {
      if (
        message.type !== "assistant" ||
        message.alternateAssistantID === null
      ) {
        return false;
      }
      const alternateAssistant = availableAssistants.find(
        (assistant) => assistant.id === message.alternateAssistantID
      );
      return alternateAssistant
        ? personaIncludesRetrieval(alternateAssistant)
        : false;
    }) || personaIncludesRetrieval(livePersona);

  return response;
}

export function personaIncludesRetrieval(
  selectedPersona: MinimalPersonaSnapshot
) {
  return selectedPersona.tools.some(
    (tool) =>
      tool.in_code_tool_id &&
      [SEARCH_TOOL_ID, WEB_SEARCH_TOOL_ID].includes(tool.in_code_tool_id)
  );
}

export function personaIncludesImage(selectedPersona: MinimalPersonaSnapshot) {
  return selectedPersona.tools.some(
    (tool) =>
      tool.in_code_tool_id && tool.in_code_tool_id == IMAGE_GENERATION_TOOL_ID
  );
}

const PARAMS_TO_SKIP = [
  SEARCH_PARAM_NAMES.SUBMIT_ON_LOAD,
  SEARCH_PARAM_NAMES.USER_PROMPT,
  SEARCH_PARAM_NAMES.TITLE,
  // only use these if explicitly passed in
  SEARCH_PARAM_NAMES.CHAT_ID,
  SEARCH_PARAM_NAMES.PERSONA_ID,
  SEARCH_PARAM_NAMES.PROJECT_ID,
  // do not persist project context in the URL after navigation
  "projectid",
];

export function buildChatUrl(
  existingSearchParams: ReadonlyURLSearchParams | null,
  chatSessionId: string | null,
  personaId: number | null,
  search?: boolean,
  skipReload?: boolean
) {
  const finalSearchParams: string[] = [];
  if (chatSessionId) {
    finalSearchParams.push(
      `${
        search ? SEARCH_PARAM_NAMES.SEARCH_ID : SEARCH_PARAM_NAMES.CHAT_ID
      }=${chatSessionId}`
    );
  }
  if (personaId !== null) {
    finalSearchParams.push(`${SEARCH_PARAM_NAMES.PERSONA_ID}=${personaId}`);
  }

  existingSearchParams?.forEach((value, key) => {
    if (!PARAMS_TO_SKIP.includes(key)) {
      finalSearchParams.push(`${key}=${value}`);
    }
  });

  if (skipReload) {
    finalSearchParams.push(`${SEARCH_PARAM_NAMES.SKIP_RELOAD}=true`);
  }

  const finalSearchParamsString = finalSearchParams.join("&");

  if (finalSearchParamsString) {
    return `/${search ? "search" : "chat"}?${finalSearchParamsString}`;
  }

  return `/${search ? "search" : "chat"}`;
}

export async function uploadFilesForChat(
  files: File[]
): Promise<[FileDescriptor[], string | null]> {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file);
  });

  const response = await fetch("/api/chat/file", {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    return [[], `Failed to upload files - ${(await response.json()).detail}`];
  }
  const responseJson = await response.json();

  return [responseJson.files as FileDescriptor[], null];
}

export function useScrollonStream({
  chatState,
  scrollableDivRef,
  scrollDist,
  endDivRef,
  debounceNumber,
  mobile,
  enableAutoScroll,
}: {
  chatState: ChatState;
  scrollableDivRef: RefObject<HTMLDivElement>;
  scrollDist: MutableRefObject<number>;
  endDivRef: RefObject<HTMLDivElement>;
  debounceNumber: number;
  mobile?: boolean;
  enableAutoScroll?: boolean;
}) {
  const mobileDistance = 900; // distance that should "engage" the scroll
  const desktopDistance = 500; // distance that should "engage" the scroll

  const distance = mobile ? mobileDistance : desktopDistance;

  const preventScrollInterference = useRef<boolean>(false);
  const preventScroll = useRef<boolean>(false);
  const blockActionRef = useRef<boolean>(false);
  const previousScroll = useRef<number>(0);

  useEffect(() => {
    if (!enableAutoScroll) {
      return;
    }

    if (chatState != "input" && scrollableDivRef && scrollableDivRef.current) {
      const newHeight: number = scrollableDivRef.current?.scrollTop!;
      const heightDifference = newHeight - previousScroll.current;
      previousScroll.current = newHeight;

      // Prevent streaming scroll
      if (heightDifference < 0 && !preventScroll.current) {
        scrollableDivRef.current.style.scrollBehavior = "auto";
        scrollableDivRef.current.scrollTop = scrollableDivRef.current.scrollTop;
        scrollableDivRef.current.style.scrollBehavior = "smooth";
        preventScrollInterference.current = true;
        preventScroll.current = true;

        setTimeout(() => {
          preventScrollInterference.current = false;
        }, 2000);
        setTimeout(() => {
          preventScroll.current = false;
        }, 10000);
      }

      // Ensure can scroll if scroll down
      else if (!preventScrollInterference.current) {
        preventScroll.current = false;
      }
      if (
        scrollDist.current < distance &&
        !blockActionRef.current &&
        !blockActionRef.current &&
        !preventScroll.current &&
        endDivRef &&
        endDivRef.current
      ) {
        // catch up if necessary!
        const scrollAmount = scrollDist.current + (mobile ? 1000 : 10000);
        if (scrollDist.current > 300) {
          // if (scrollDist.current > 140) {
          endDivRef.current.scrollIntoView();
        } else {
          blockActionRef.current = true;

          scrollableDivRef?.current?.scrollBy({
            left: 0,
            top: Math.max(0, scrollAmount),
            behavior: "smooth",
          });

          setTimeout(() => {
            blockActionRef.current = false;
          }, debounceNumber);
        }
      }
    }
  });

  // scroll on end of stream if within distance
  useEffect(() => {
    if (scrollableDivRef?.current && chatState == "input" && enableAutoScroll) {
      if (scrollDist.current < distance - 50) {
        scrollableDivRef?.current?.scrollBy({
          left: 0,
          top: Math.max(scrollDist.current + 600, 0),
          behavior: "smooth",
        });
      }
    }
  }, [chatState, distance, scrollDist, scrollableDivRef, enableAutoScroll]);
}
