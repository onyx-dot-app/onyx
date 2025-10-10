import { ChatSearchRequest, ChatSearchResponse } from "./interfaces";

const API_BASE_URL = "/api";

export interface ExtendedChatSearchRequest extends ChatSearchRequest {
  include_highlights?: boolean;
  signal?: AbortSignal;
}

export async function fetchChatSessions(
  params: ExtendedChatSearchRequest = {}
): Promise<ChatSearchResponse> {
  const queryParams = new URLSearchParams();

  if (params.query) {
    queryParams.append("query", params.query);
  }

  if (params.page) {
    queryParams.append("page", params.page.toString());
  }

  if (params.page_size) {
    queryParams.append("page_size", params.page_size.toString());
  }

  if (params.include_highlights !== undefined) {
    queryParams.append(
      "include_highlights",
      params.include_highlights.toString()
    );
  }

  const queryString = queryParams.toString()
    ? `?${queryParams.toString()}`
    : "";

  const response = await fetch(`${API_BASE_URL}/chat/search${queryString}`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch chat sessions: ${response.statusText}`);
  }

  return response.json();
}

export async function createNewChat(): Promise<{ chat_session_id: string }> {
  const response = await fetch(`${API_BASE_URL}/chat/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });

  if (!response.ok) {
    throw new Error(`Failed to create new chat: ${response.statusText}`);
  }

  return response.json();
}

export async function deleteChat(chatId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/chat/sessions/${chatId}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to delete chat: ${response.statusText}`);
  }
}

export async function stopChatSession(chatSessionId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/chat/stop-chat-session/${chatSessionId}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to stop chat session: ${response.statusText}`);
  }
}
