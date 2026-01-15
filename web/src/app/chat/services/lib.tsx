import {
  Filters,
  DocumentInfoPacket,
  StreamStopInfo,
} from "@/lib/search/interfaces";
import { handleSSEStream } from "@/lib/search/streamingUtils";
import { ChatState, FeedbackType } from "@/app/chat/interfaces";
import { MutableRefObject, RefObject, useEffect, useRef } from "react";
import {
  BackendMessage,
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
import { WEB_SEARCH_TOOL_ID } from "@/app/chat/components/tools/constants";
import { SEARCH_TOOL_ID } from "@/app/chat/components/tools/constants";
import { Packet } from "./streamingModels";

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

// Origin of the message for telemetry tracking.
// Keep in sync with backend: backend/onyx/server/query_and_chat/models.py::MessageOrigin
export type MessageOrigin =
  | "webapp"
  | "chrome_extension"
  | "api"
  | "slackbot"
  | "unknown";

export interface SendMessageParams {
  message: string;
  fileDescriptors?: FileDescriptor[];
  parentMessageId: number | null;
  chatSessionId: string;
  filters: Filters | null;
  signal?: AbortSignal;
  deepResearch?: boolean;
  enabledToolIds?: number[];
  // Single forced tool ID (new API uses singular, not array)
  forcedToolId?: number | null;
  // LLM override parameters
  modelProvider?: string;
  modelVersion?: string;
  temperature?: number;
  // Origin of the message for telemetry tracking
  origin?: MessageOrigin;
}

export async function* sendMessage({
  message,
  fileDescriptors,
  parentMessageId,
  chatSessionId,
  filters,
  signal,
  deepResearch,
  enabledToolIds,
  forcedToolId,
  modelProvider,
  modelVersion,
  temperature,
  origin,
}: SendMessageParams): AsyncGenerator<PacketType, void, unknown> {
  // Build payload for new send-chat-message API
  const payload = {
    message: message,
    chat_session_id: chatSessionId,
    parent_message_id: parentMessageId,
    file_descriptors: fileDescriptors,
    internal_search_filters: filters,
    deep_research: deepResearch ?? false,
    allowed_tool_ids: enabledToolIds,
    forced_tool_id: forcedToolId ?? null,
    llm_override:
      temperature || modelVersion
        ? {
            temperature,
            model_provider: modelProvider,
            model_version: modelVersion,
          }
        : null,
    // Default to "unknown" for consistency with backend; callers should set explicitly
    origin: origin ?? "unknown",
  };

  const body = JSON.stringify(payload);

  const response = await fetch(`/api/chat/send-chat-message`, {
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

export async function removeChatFeedback(messageId: number) {
  const response = await fetch(
    `/api/chat/remove-chat-message-feedback?chat_message_id=${messageId}`,
    {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
      },
    }
  );
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

    const hasContextDocs = (messageInfo?.context_docs || []).length > 0;
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
            documents: messageInfo?.context_docs || [],
            citations: messageInfo?.citations || {},
          }
        : {}),
      toolCall: messageInfo.tool_call,
      parentNodeId: messageInfo.parent_message,
      childrenNodeIds: [],
      latestChildNodeId: messageInfo.latest_child_message,
      overridden_model: messageInfo.overridden_model,
      packets: packetsForMessage || [],
      currentFeedback: messageInfo.current_feedback as FeedbackType | null,
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

export function personaIncludesRetrieval(
  selectedPersona: MinimalPersonaSnapshot
) {
  return selectedPersona.tools.some(
    (tool) =>
      tool.in_code_tool_id &&
      [SEARCH_TOOL_ID, WEB_SEARCH_TOOL_ID].includes(tool.in_code_tool_id)
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
  scrollableDivRef: RefObject<HTMLDivElement | null>;
  scrollDist: MutableRefObject<number>;
  endDivRef: RefObject<HTMLDivElement | null>;
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
