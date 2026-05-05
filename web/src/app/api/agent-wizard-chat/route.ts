import { INTERNAL_URL } from "@/lib/constants";
import { NextRequest, NextResponse } from "next/server";

interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

interface AgentWizardChatRequest {
  messages: ChatMessage[];
  currentValues: Record<string, unknown>;
}

interface LLMProviderView {
  id: number;
  name: string;
  provider: string;
  api_key: string | null;
  api_base: string | null;
  api_version: string | null;
  custom_config: Record<string, string> | null;
  model_configurations: { name: string; is_visible: boolean }[];
  is_default_provider: boolean | null;
}

interface LLMProviderResponse {
  providers: LLMProviderView[];
  default_text: { provider_id: number; model_name: string } | null;
  default_vision: { provider_id: number; model_name: string } | null;
}

const SYSTEM_PROMPT = `You are a helpful assistant inside an AI agent builder. Your role is to help users design and configure an AI agent through natural conversation.

When a user describes what they want, you:
1. Acknowledge what you understood in a friendly, concise way
2. Suggest any improvements or ask a single focused follow-up question if something important is missing
3. At the very end of your response, emit a structured field block so the form updates automatically

Keep responses short (2-4 sentences). Be warm and direct — not overly formal.

The field block must appear at the END of your response, after all conversational text. Format:
<<<FIELDS>>>
{ "field": "value", ... }
<<<END>>>

Available fields:
- name (string): Short, memorable agent name (2-5 words)
- description (string): One-sentence summary of what the agent does, max 300 chars
- instructions (string): The agent's system prompt — its persona, behavior, tone, and constraints. Be specific and detailed.
- starter_messages (string[]): 3-5 example prompts users might send this agent, each max 200 chars
- web_search (boolean): true if the agent needs to look up current information
- image_generation (boolean): true if the agent creates images
- code_interpreter (boolean): true if the agent writes or runs code

Rules:
- Always emit the <<<FIELDS>>>...<<<END>>> block, even if only one field changed.
- Only include fields that need to change based on the conversation.
- On the first message, extract as many fields as you can from the user's description.
- The JSON inside the block must be valid — no trailing commas, no comments.
- Do NOT include the field block mid-response. It must be at the very end.`;


/**
 * Build forwarding headers, injecting debug auth cookie in dev mode
 * (same pattern as the catch-all proxy in [...path]/route.ts).
 */
function buildHeaders(request: NextRequest): Headers {
  const headers = new Headers(request.headers);
  if (
    process.env.DEBUG_AUTH_COOKIE &&
    process.env.NODE_ENV === "development"
  ) {
    const existing = headers.get("cookie") || "";
    const debug = `fastapiusersauth=${process.env.DEBUG_AUTH_COOKIE}`;
    headers.set("cookie", existing ? `${existing}; ${debug}` : debug);
  }
  return headers;
}

/**
 * Fetch LLM providers from the Onyx backend using the admin endpoint.
 */
async function fetchLLMProviders(
  headers: Headers
): Promise<LLMProviderResponse> {
  const url = `${INTERNAL_URL}/admin/llm/provider`;
  const res = await fetch(url, {
    method: "GET",
    headers,
  });
  if (!res.ok) {
    throw new Error(
      `Failed to fetch LLM providers: ${res.status} ${res.statusText}`
    );
  }
  return res.json();
}

/**
 * Pick the best provider+model to use.
 * Preference: OpenAI > default text provider > first provider with visible models.
 */
function pickProvider(data: LLMProviderResponse): {
  provider: LLMProviderView;
  model: string;
  providerType: string;
} {
  const { providers, default_text } = data;

  if (!providers || providers.length === 0) {
    throw new Error("No LLM providers configured");
  }

  // 1. Prefer OpenAI
  const openai = providers.find((p) => p.provider === "openai");
  if (openai) {
    const model =
      openai.model_configurations.find((m) => m.is_visible)?.name ||
      "gpt-4o-mini";
    return { provider: openai, model, providerType: "openai" };
  }

  // 2. Fall back to the default text provider
  if (default_text) {
    const defaultProvider = providers.find(
      (p) => p.id === default_text.provider_id
    );
    if (defaultProvider) {
      return {
        provider: defaultProvider,
        model: default_text.model_name,
        providerType: defaultProvider.provider,
      };
    }
  }

  // 3. Fall back to first provider with a visible model
  for (const p of providers) {
    const visibleModel = p.model_configurations.find((m) => m.is_visible);
    if (visibleModel) {
      return { provider: p, model: visibleModel.name, providerType: p.provider };
    }
  }

  // 4. Last resort: first provider, first model
  const first = providers[0]!;
  const model = first.model_configurations[0]?.name || "gpt-4o-mini";
  return { provider: first, model, providerType: first.provider };
}

/**
 * Call an OpenAI-compatible API with streaming.
 */
async function callOpenAI(
  apiKey: string,
  apiBase: string,
  model: string,
  messages: ChatMessage[]
): Promise<Response> {
  const url = `${apiBase}/chat/completions`;
  return fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      messages,
      stream: true,
    }),
  });
}

/**
 * Call the Anthropic Messages API with streaming.
 */
async function callAnthropic(
  apiKey: string,
  model: string,
  messages: ChatMessage[]
): Promise<Response> {
  // Anthropic requires the system prompt as a top-level param, not in messages
  const systemContent = messages
    .filter((m) => m.role === "system")
    .map((m) => m.content)
    .join("\n\n");

  const nonSystemMessages = messages
    .filter((m) => m.role !== "system")
    .map((m) => ({ role: m.role, content: m.content }));

  return fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model,
      max_tokens: 4096,
      system: systemContent,
      messages: nonSystemMessages,
      stream: true,
    }),
  });
}

export async function POST(request: NextRequest) {
  try {
    const body: AgentWizardChatRequest = await request.json();
    const { messages, currentValues } = body;

    if (!messages || !Array.isArray(messages)) {
      return NextResponse.json(
        { error: "messages array is required" },
        { status: 400 }
      );
    }

    // Fetch LLM providers from backend
    const headers = buildHeaders(request);
    const providerData = await fetchLLMProviders(headers);
    const { provider, model, providerType } = pickProvider(providerData);

    if (!provider.api_key) {
      return NextResponse.json(
        { error: "Selected LLM provider has no API key configured" },
        { status: 500 }
      );
    }

    // Build message list with system prompt
    const safeValues = currentValues ?? {};
    const systemMessage: ChatMessage = {
      role: "system",
      content: `${SYSTEM_PROMPT}\n\nCurrent form values:\n${JSON.stringify(safeValues, null, 2)}`,
    };
    const fullMessages = [systemMessage, ...messages];

    // Call the appropriate LLM API with streaming
    let llmResponse: Response;

    if (providerType === "anthropic") {
      llmResponse = await callAnthropic(provider.api_key, model, fullMessages);
    } else {
      // OpenAI-compatible (covers openai, azure, litellm, etc.)
      const apiBase = provider.api_base || "https://api.openai.com/v1";
      llmResponse = await callOpenAI(
        provider.api_key,
        apiBase,
        model,
        fullMessages
      );
    }

    if (!llmResponse.ok) {
      const errorText = await llmResponse.text();
      console.error(
        `LLM API error (${providerType}/${model}):`,
        llmResponse.status,
        errorText
      );
      return NextResponse.json(
        {
          error: `LLM API returned ${llmResponse.status}`,
          detail: errorText,
        },
        { status: 502 }
      );
    }

    // Forward the raw SSE stream back to the client
    if (!llmResponse.body) {
      return NextResponse.json(
        { error: "No response body from LLM" },
        { status: 502 }
      );
    }

    const responseHeaders = new Headers();
    responseHeaders.set("Content-Type", "text/event-stream");
    responseHeaders.set("Cache-Control", "no-cache");
    responseHeaders.set("Connection", "keep-alive");
    // Pass through the provider type so the client knows how to parse the stream
    responseHeaders.set("X-LLM-Provider", providerType);

    return new Response(llmResponse.body, {
      status: 200,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error("agent-wizard-chat error:", error);
    return NextResponse.json(
      {
        error: "Internal server error",
        detail: error instanceof Error ? error.message : "Unknown error",
      },
      { status: 500 }
    );
  }
}
