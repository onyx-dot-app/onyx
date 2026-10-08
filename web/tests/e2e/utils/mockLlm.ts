/**
 * Client for the scripted mock LLM server
 * (`backend/tests/integration/mock_services/mock_llm_server/server.py`),
 * which answers every LLM call of the Playwright deployment.
 *
 * Global setup registers the `default` script. Its default reply answers
 * every request that no conversation serves, including all tool-free
 * secondary calls (session naming, query expansion, filters). To script a
 * turn, add a conversation to the default script that matches a nonce, and put
 * that nonce in the chat message:
 *
 * ```ts
 * const nonce = mockLlmNonce();
 * await addMockLlmConversation({
 *   name: nonce,
 *   conditions: { prompt_contains: [nonce] },
 *   replies: [{ tool_calls: [{ id: `call-${nonce}`, name: "tool_0" }] }],
 * });
 * await sendMessage(page, `Run the tool. ${nonce}`);
 * ```
 *
 * The nonce keeps the conversation out of other workers' chat turns, so specs never
 * change the shared default provider.
 */

import { randomUUID } from "crypto";

/** Where the Playwright runner reaches the mock LLM server. */
export const MOCK_LLM_SERVER_URL =
  process.env.MOCK_LLM_SERVER_URL || "http://localhost:8095";
/** Where the Onyx backend reaches the mock LLM server. */
export const MOCK_LLM_BACKEND_URL =
  process.env.MOCK_LLM_BACKEND_URL || "http://mock_llm_server:8095";

export const MOCK_LLM_DEFAULT_SCRIPT_ID = "default";
export const MOCK_LLM_DEFAULT_RESPONSE = "This is a mock LLM response.";
export const MOCK_LLM_PROVIDER_NAME = "PW Mock LLM";
export const MOCK_LLM_API_KEY = "sk-mock-llm-server";
// Deep Research needs at least 50000 input tokens.
export const MOCK_LLM_MAX_INPUT_TOKENS = 200000;
// Neutral names: Onyx special-cases catalog names and names that contain
// claude, qwen, glm, or gpt-5.x.
export const MOCK_LLM_MODELS = [
  { name: "mock-model", displayName: "Mock Model" },
  { name: "mock-model-alt", displayName: "Mock Alt Model" },
] as const;
export const MOCK_LLM_DEFAULT_MODEL = MOCK_LLM_MODELS[0];

const HEALTH_TIMEOUT_MS = 30_000;
const HEALTH_POLL_INTERVAL_MS = 1_000;

export interface MockLlmToolCall {
  id: string;
  name: string;
  arguments?: Record<string, unknown>;
}

/**
 * Every set field must hold. A tool-free request (no tools and no tool
 * results, for example session naming) goes only to a reply whose
 * conversation or reply `conditions` set `has_tools: false`; otherwise it gets the
 * default reply.
 */
export interface MockLlmRequestConditions {
  has_tools?: boolean;
  offers?: string[];
  does_not_offer?: string[];
  has_results_for?: string[];
  tool_choice?: "auto" | "required" | "none";
  prompt_contains?: string[];
}

export interface MockLlmReply {
  pause_after_first_chunk?: string;
  reasoning?: string;
  text?: string;
  tool_calls?: MockLlmToolCall[];
  conditions?: MockLlmRequestConditions;
  required?: boolean;
}

export interface MockLlmConversation {
  name: string;
  conditions?: MockLlmRequestConditions;
  replies: MockLlmReply[];
}

export interface MockLlmScript {
  conversations?: MockLlmConversation[];
  default_reply?: MockLlmReply | null;
}

/** The `api_base` of a provider that the given script answers. */
export function mockLlmApiBase(
  scriptId: string = MOCK_LLM_DEFAULT_SCRIPT_ID
): string {
  return `${MOCK_LLM_BACKEND_URL}/scripts/${scriptId}/v1`;
}

/** A unique token to put in a chat message and match with `prompt_contains`. */
export function mockLlmNonce(): string {
  return `pw-${randomUUID()}`;
}

/** Wait until the mock LLM server answers its health check. */
export async function waitForMockLlmServer(): Promise<void> {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${MOCK_LLM_SERVER_URL}/health`);
      if (response.ok) {
        return;
      }
    } catch {
      // Not up yet.
    }
    await new Promise((resolve) =>
      setTimeout(resolve, HEALTH_POLL_INTERVAL_MS)
    );
  }
  throw new Error(
    `The mock LLM server is not reachable at ${MOCK_LLM_SERVER_URL}. Start it ` +
      "with the docker-compose.mock-llm-test.yml overlay (see web/tests/e2e/README.md)."
  );
}

async function sendControlRequest(
  method: "PUT" | "POST",
  path: string,
  body: MockLlmScript | MockLlmConversation,
  description: string
): Promise<void> {
  const response = await fetch(`${MOCK_LLM_SERVER_URL}${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(
      `Failed to ${description}: ${response.status} ${await response.text()}`
    );
  }
}

/**
 * Create or replace the default script, with no conversations and a default
 * reply that answers every other request. Replacing it drops the
 * conversations of running specs, so only global setup calls this.
 */
export async function putMockLlmDefaultScript(): Promise<void> {
  await sendControlRequest(
    "PUT",
    `/scripts/${MOCK_LLM_DEFAULT_SCRIPT_ID}`,
    { conversations: [], default_reply: { text: MOCK_LLM_DEFAULT_RESPONSE } },
    "register the default mock LLM script"
  );
}

/**
 * Add a conversation to a script. Conversations are served before the
 * script's default reply.
 */
export async function addMockLlmConversation(
  conversation: MockLlmConversation,
  scriptId: string = MOCK_LLM_DEFAULT_SCRIPT_ID
): Promise<void> {
  await sendControlRequest(
    "POST",
    `/scripts/${scriptId}/conversations`,
    conversation,
    `add mock LLM conversation ${conversation.name}`
  );
}

/** Release a paused reply after the browser has reached the state under test. */
export async function releaseMockLlmGate(gateId: string): Promise<void> {
  const response = await fetch(
    `${MOCK_LLM_SERVER_URL}/scripts/${MOCK_LLM_DEFAULT_SCRIPT_ID}/gates/${encodeURIComponent(gateId)}/release`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw new Error(
      `Failed to release mock LLM gate: ${response.status} ${await response.text()}`
    );
  }
}

interface MockLlmRecordedRequest {
  conversation: string | null;
  messages: { role: string; content: string; tool_call_id: string | null }[];
}

/** Read actual model inputs for one scripted conversation. */
export async function getMockLlmConversationRequests(
  name: string
): Promise<MockLlmRecordedRequest[]> {
  const response = await fetch(
    `${MOCK_LLM_SERVER_URL}/scripts/${MOCK_LLM_DEFAULT_SCRIPT_ID}`
  );
  if (!response.ok)
    throw new Error(`Failed to read mock LLM requests: ${response.status}`);
  const state: { requests: MockLlmRecordedRequest[] } = await response.json();
  return state.requests.filter((request) => request.conversation === name);
}
