/**
 * API Service - Handles all communication with Onyx backend
 */

import {
  Packet,
  CreateSessionRequest,
  CreateSessionResponse,
  SendMessageRequest,
} from "@/types/api-types";

export class ApiService {
  private maxRetries = 3;
  private retryDelay = 1000;

  constructor(
    private backendUrl: string,
    private apiKey: string,
  ) {}

  /**
   * Create a new chat session
   */
  async createChatSession(agentId?: number): Promise<string> {
    const request: CreateSessionRequest = {};
    if (agentId !== undefined) {
      request.persona_id = agentId;
    }

    const response = await this.fetchWithRetry(
      `${this.backendUrl}/chat/create-chat-session`,
      {
        method: "POST",
        headers: this.getHeaders(),
        body: JSON.stringify(request),
      },
    );

    if (!response.ok) {
      throw new Error(
        `Failed to create session: ${response.status} ${response.statusText}`,
      );
    }

    const data = (await response.json()) as CreateSessionResponse;
    return data.chat_session_id;
  }

  /**
   * Stream a message to the chat
   * Returns an async generator of packets
   */
  async *streamMessage(params: {
    message: string;
    chatSessionId: string;
    parentMessageId?: number | null;
    signal?: AbortSignal;
    includeCitations?: boolean;
  }): AsyncGenerator<Packet, void, unknown> {
    const request: SendMessageRequest = {
      message: params.message,
      chat_session_id: params.chatSessionId,
      parent_message_id: params.parentMessageId ?? null,
      origin: "widget",
      include_citations: params.includeCitations ?? false,
    };

    const response = await this.fetchWithRetry(
      `${this.backendUrl}/chat/send-chat-message`,
      {
        method: "POST",
        headers: this.getHeaders(),
        body: JSON.stringify(request),
        signal: params.signal,
      },
    );

    if (!response.ok) {
      throw new Error(
        `Failed to send message: ${response.status} ${response.statusText}`,
      );
    }

    // Parse SSE stream
    yield* this.parseSSEStream(response);
  }

  /**
   * Parse Server-Sent Events stream
   * Backend returns newline-delimited JSON packets
   */
  private async *parseSSEStream(
    response: Response,
  ): AsyncGenerator<Packet, void, unknown> {
    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("Response body is not readable");
    }

    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || ""; // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.trim()) {
            try {
              const rawData = JSON.parse(line);

              // Check if this is a MessageResponseIDInfo (not wrapped in Packet)
              if (
                "user_message_id" in rawData &&
                "reserved_assistant_message_id" in rawData
              ) {
                // Wrap it in a Packet structure for consistent handling
                const packet: Packet = {
                  obj: rawData as any,
                };
                yield packet;
              } else {
                // Regular packet with placement and obj
                yield rawData as Packet;
              }
            } catch (e) {
              // Fail fast on malformed packets - don't hide backend issues
              throw new Error(
                `Failed to parse SSE packet: ${line}. Error: ${e}`,
              );
            }
          }
        }
      }

      // Process any remaining data in buffer
      if (buffer.trim()) {
        try {
          const rawData = JSON.parse(buffer);

          // Check if this is a MessageResponseIDInfo (not wrapped in Packet)
          if (
            "user_message_id" in rawData &&
            "reserved_assistant_message_id" in rawData
          ) {
            const packet: Packet = {
              obj: rawData as any,
            };
            yield packet;
          } else {
            yield rawData as Packet;
          }
        } catch (e) {
          // Fail fast on malformed final buffer packets
          throw new Error(
            `Failed to parse final packet: ${buffer}. Error: ${e}`,
          );
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  /**
   * Fetch with retry logic for network failures and 5xx errors
   */
  private async fetchWithRetry(
    url: string,
    options: RequestInit,
    retries = 0,
  ): Promise<Response> {
    try {
      const response = await fetch(url, options);

      // Retry on 5xx or 429 errors
      if (!response.ok && retries < this.maxRetries) {
        if (response.status >= 500 || response.status === 429) {
          const delay = this.retryDelay * Math.pow(2, retries);
          await new Promise((resolve) => setTimeout(resolve, delay));
          return this.fetchWithRetry(url, options, retries + 1);
        }
      }

      return response;
    } catch (error) {
      // Don't retry if the request was aborted by the caller
      if (error instanceof Error && error.name === "AbortError") {
        throw error;
      }

      // Retry on network errors
      if (retries < this.maxRetries) {
        const delay = this.retryDelay * Math.pow(2, retries);
        await new Promise((resolve) => setTimeout(resolve, delay));
        return this.fetchWithRetry(url, options, retries + 1);
      }
      throw error;
    }
  }

  /**
   * Get common headers for API requests
   */
  private getHeaders(): Record<string, string> {
    return {
      "Content-Type": "application/json",
      Authorization: `Bearer ${this.apiKey}`,
    };
  }
}
