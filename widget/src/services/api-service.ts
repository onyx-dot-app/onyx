/**
 * API Service - Handles all communication with Onyx backend
 */

import {
  ApprovalDecisionResponse,
  ChatSessionDetail,
  ChatSessionStatus,
  ChatStream,
  MessageResponseIDInfo,
  Packet,
  StreamCursor,
  CreateSessionRequest,
  CreateSessionResponse,
  SendMessageRequest,
} from "@/types/api-types";
import { TokenProvider } from "@/types/widget-types";
import type { ApprovalDecision } from "@/services/approvals";

const READINESS_REQUEST_TIMEOUT_MS = 10_000;
export const READINESS_POLL_INTERVAL_MS = 1_000;

/** Resolves after `ms`, or at once when `signal` aborts. */
export function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise<void>((resolve) => {
    const onAbort = () => {
      clearTimeout(timer);
      resolve();
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

class SessionUnavailableError extends Error {}

/** How a resume attempt ended without throwing. */
export type ResumeEnd = "noBuffer" | "ended";

/** A rejected request, with the backend's `error_code` when it sent one. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly errorCode?: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiErrorFrom(response: Response): Promise<ApiError> {
  let detail = response.statusText;
  let errorCode: string | undefined;
  try {
    const body = await response.json();
    if (body.detail) detail = body.detail;
    if (typeof body.error_code === "string") errorCode = body.error_code;
  } catch {
    // Fall back to statusText if body isn't JSON
  }
  return new ApiError(detail, response.status, errorCode);
}

export class ApiService {
  private maxRetries = 3;
  private retryDelay = 1000;

  constructor(
    private backendUrl: string,
    private resolveToken: TokenProvider
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
      async () => ({
        method: "POST",
        headers: await this.getHeaders(),
        body: JSON.stringify(request),
      })
    );

    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        if (body.detail) {
          detail = body.detail;
        }
      } catch {
        // Fall back to statusText if body isn't JSON
      }
      throw new Error(detail);
    }

    const data = (await response.json()) as CreateSessionResponse;
    return data.chat_session_id;
  }

  /**
   * Polls the session status until the session is idle, or until it runs a
   * stream that `attachable` accepts. Returns the status read that ended the
   * wait.
   */
  async waitForSessionIdle(
    sessionId: string,
    signal: AbortSignal,
    onUnconfirmed: () => void,
    attachable: (stream: ChatStream) => boolean = () => false
  ): Promise<ChatSessionStatus> {
    let authenticationFailures = 0;
    while (!signal.aborted) {
      const controller = new AbortController();
      const onAbort = () => controller.abort();
      signal.addEventListener("abort", onAbort, { once: true });
      const timeout = setTimeout(onAbort, READINESS_REQUEST_TIMEOUT_MS);
      const aborted = new Promise<never>((_, reject) => {
        controller.signal.addEventListener(
          "abort",
          () => reject(new DOMException("Request cancelled", "AbortError")),
          { once: true }
        );
      });
      try {
        const response = await fetch(
          `${this.backendUrl}/chat/chat-session/${sessionId}/status`,
          {
            headers: await Promise.race([this.getHeaders(), aborted]),
            signal: controller.signal,
          }
        );
        if (response.status === 401) {
          authenticationFailures += 1;
          if (authenticationFailures >= this.maxRetries) {
            throw new SessionUnavailableError(
              "Authentication failed. Reload the page to sign in again."
            );
          }
        } else {
          authenticationFailures = 0;
        }
        if (response.status === 405) {
          throw new SessionUnavailableError(
            "This server does not support chat readiness checks. Contact your administrator."
          );
        }
        if (response.status === 403 || response.status === 404) {
          throw new SessionUnavailableError(
            "This conversation is no longer available. Start a new conversation."
          );
        }
        if (!response.ok) throw new Error("Cannot confirm chat readiness");
        const status = readChatSessionStatus(await response.json());
        if (
          !status.is_processing ||
          (status.current_stream !== null && attachable(status.current_stream))
        )
          return status;
      } catch (error) {
        if (signal.aborted || error instanceof SessionUnavailableError)
          throw error;
        onUnconfirmed();
      } finally {
        clearTimeout(timeout);
        signal.removeEventListener("abort", onAbort);
      }
      if (signal.aborted) break;
      await pause(READINESS_POLL_INTERVAL_MS, signal);
    }
    throw new DOMException("Request cancelled", "AbortError");
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
  }): AsyncGenerator<Packet | StreamCursor, void, unknown> {
    const request: SendMessageRequest = {
      message: params.message,
      chat_session_id: params.chatSessionId,
      parent_message_id: params.parentMessageId ?? null,
      origin: "widget",
      include_citations: params.includeCitations ?? false,
    };

    const response = await this.fetchWithRetry(
      `${this.backendUrl}/chat/send-chat-message`,
      async () => ({
        method: "POST",
        headers: await this.getHeaders(),
        body: JSON.stringify(request),
        signal: params.signal,
      })
    );

    if (!response.ok) {
      throw await apiErrorFrom(response);
    }

    // Parse SSE stream
    yield* this.parseSSEStream(response);
  }

  /**
   * Replay the session's running response from `from.cursor` of stream
   * `from.streamId`, or from the start of the current stream, then follow it.
   * Returns "noBuffer" without packets when the server has nothing to serve
   * at that cursor (404), else "ended" when the body ends. Other failures
   * throw.
   */
  async *resumeStream(
    chatSessionId: string,
    signal: AbortSignal,
    from: { streamId: number; cursor: number } | null = null
  ): AsyncGenerator<Packet | StreamCursor, ResumeEnd, unknown> {
    const query = from
      ? `stream_id=${from.streamId}&cursor=${from.cursor}`
      : "cursor=0";
    const response = await this.fetchWithRetry(
      `${this.backendUrl}/chat/chat-session/${encodeURIComponent(chatSessionId)}/resume-stream?${query}`,
      async () => ({ headers: await this.getHeaders(), signal })
    );
    if (response.status === 404) return "noBuffer";
    if (!response.ok) throw await apiErrorFrom(response);
    yield* this.parseSSEStream(response);
    return "ended";
  }

  /** The session's saved messages, with a replay packet list for each response. */
  async getChatSession(
    chatSessionId: string,
    signal: AbortSignal
  ): Promise<ChatSessionDetail> {
    const response = await this.fetchWithRetry(
      `${this.backendUrl}/chat/get-chat-session/${encodeURIComponent(chatSessionId)}`,
      async () => ({ headers: await this.getHeaders(), signal })
    );
    if (!response.ok) throw await apiErrorFrom(response);
    const body: unknown = await response.json();
    if (
      typeof body !== "object" ||
      body === null ||
      !("messages" in body) ||
      !Array.isArray(body.messages) ||
      !("packets" in body) ||
      !Array.isArray(body.packets)
    ) {
      throw new Error("Invalid chat session response");
    }
    return body as ChatSessionDetail;
  }

  /**
   * Submit a decision on a tool call's approval request. Returns "closed"
   * when the request no longer waits for a decision (404 or 409). A response
   * names the stream that continues the turn when the decision resumed it.
   */
  async submitApprovalDecision(
    approvalId: string,
    decision: ApprovalDecision
  ): Promise<ApprovalDecisionResponse | "closed"> {
    // No retry: a repeated decision on a decided request only returns 409.
    const response = await fetch(
      `${this.backendUrl}/chat/approvals/${encodeURIComponent(approvalId)}/decision`,
      {
        method: "POST",
        headers: await this.getHeaders(),
        body: JSON.stringify({ decision }),
      }
    );
    if (response.status === 404 || response.status === 409) return "closed";
    if (!response.ok) throw await apiErrorFrom(response);
    const body: unknown = await response.json();
    if (
      typeof body !== "object" ||
      body === null ||
      !("decision" in body) ||
      (body.decision !== "APPROVED" && body.decision !== "REJECTED") ||
      !("decided_via" in body) ||
      typeof body.decided_via !== "string"
    ) {
      throw new Error("Invalid approval decision response");
    }
    const continuation =
      "continuation" in body ? readChatStream(body.continuation) : null;
    return {
      decision: body.decision,
      decided_via: body.decided_via,
      continuation,
    };
  }

  /**
   * Parse the NDJSON stream. A response-ID line comes without a packet
   * wrapper; a resumed stream adds its cursor lines.
   */
  private async *parseSSEStream(
    response: Response
  ): AsyncGenerator<Packet | StreamCursor, void, unknown> {
    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("Response body is not readable");
    }

    const parse = (line: string): Packet | StreamCursor => {
      try {
        const rawData = JSON.parse(line);
        if (
          "user_message_id" in rawData &&
          "reserved_assistant_message_id" in rawData
        ) {
          return { obj: rawData as MessageResponseIDInfo };
        }
        if ("next_cursor" in rawData && !("obj" in rawData)) {
          return rawData as StreamCursor;
        }
        return rawData as Packet;
      } catch (e) {
        // Fail fast on malformed packets - don't hide backend issues
        throw new Error(`Failed to parse SSE packet: ${line}. Error: ${e}`);
      }
    };

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
          if (line.trim()) yield parse(line);
        }
      }
      if (buffer.trim()) yield parse(buffer);
    } finally {
      reader.releaseLock();
    }
  }

  /**
   * Fetch with retry logic for network failures and 5xx errors.
   * Options are rebuilt per attempt so each retry carries a freshly resolved
   * credential; a short-lived token can otherwise expire during the backoff.
   */
  private async fetchWithRetry(
    url: string,
    buildOptions: () => Promise<RequestInit>,
    retries = 0
  ): Promise<Response> {
    try {
      const response = await fetch(url, await buildOptions());

      // Retry on 5xx errors only (not 4xx — those are permanent)
      if (!response.ok && retries < this.maxRetries) {
        if (response.status >= 500) {
          const delay = this.retryDelay * Math.pow(2, retries);
          await new Promise((resolve) => setTimeout(resolve, delay));
          return this.fetchWithRetry(url, buildOptions, retries + 1);
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
        return this.fetchWithRetry(url, buildOptions, retries + 1);
      }
      throw error;
    }
  }

  /**
   * Get common headers for API requests.
   * The credential is resolved per call so an expiring token can be refreshed
   * by the host between requests.
   */
  private async getHeaders(): Promise<Record<string, string>> {
    const token = await this.resolveToken();
    if (!token) {
      throw new Error("Onyx credential resolved to an empty value");
    }

    return {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    };
  }
}

/** A stream that the server names, or null for anything else. */
export function readChatStream(value: unknown): ChatStream | null {
  if (
    typeof value !== "object" ||
    value === null ||
    !("stream_id" in value) ||
    typeof value.stream_id !== "number"
  )
    return null;
  const responseIds =
    "response_ids" in value && Array.isArray(value.response_ids)
      ? value.response_ids.filter(
          (id: unknown): id is number => typeof id === "number"
        )
      : [];
  return { stream_id: value.stream_id, response_ids: responseIds };
}

/** The status fields the widget reads; throws on a response without them. */
export function readChatSessionStatus(value: unknown): ChatSessionStatus {
  if (
    typeof value !== "object" ||
    value === null ||
    !("is_processing" in value) ||
    typeof value.is_processing !== "boolean"
  ) {
    throw new Error("Invalid chat readiness response");
  }
  return {
    is_processing: value.is_processing,
    has_active_subagents:
      "has_active_subagents" in value && value.has_active_subagents === true,
    has_startable_input:
      "has_startable_input" in value && value.has_startable_input === true,
    latest_response_id:
      "latest_response_id" in value &&
      typeof value.latest_response_id === "number"
        ? value.latest_response_id
        : null,
    current_stream:
      "current_stream" in value ? readChatStream(value.current_stream) : null,
    approvals_version:
      "approvals_version" in value &&
      typeof value.approvals_version === "string"
        ? value.approvals_version
        : null,
  };
}
