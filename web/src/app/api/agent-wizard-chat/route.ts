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

export async function POST(request: NextRequest) {
  try {
    const body: AgentWizardChatRequest = await request.json();
    const { messages, currentValues } = body;

    if (!messages || !Array.isArray(messages) || messages.length === 0) {
      return NextResponse.json(
        { error: "messages array is required and cannot be empty" },
        { status: 400 }
      );
    }

    const safeValues = currentValues ?? {};
    const systemPromptWithValues = `${SYSTEM_PROMPT}\n\nCurrent form values:\n${JSON.stringify(safeValues, null, 2)}`;
    
    // Use the latest message as the prompt
    const lastMessage = messages[messages.length - 1]!;
    const previousMessages = messages.slice(0, -1);
    
    let additionalContext = `System Instructions:\n${systemPromptWithValues}\n\n`;
    if (previousMessages.length > 0) {
      additionalContext += `Previous conversation history:\n`;
      previousMessages.forEach((m) => {
        additionalContext += `${m.role.toUpperCase()}: ${m.content}\n\n`;
      });
    }

    const payload = {
      message: lastMessage.content,
      chat_session_info: {
        persona_id: 0,
      },
      additional_context: additionalContext,
      stream: true,
      include_citations: false,
    };

    const headers = buildHeaders(request);
    headers.delete("content-length");
    headers.delete("host");
    headers.set("Content-Type", "application/json");

    const onyxRes = await fetch(`${INTERNAL_URL}/chat/send-chat-message`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });

    if (!onyxRes.ok) {
      const errorText = await onyxRes.text();
      console.error("Onyx Backend API error:", onyxRes.status, errorText);
      return NextResponse.json(
        { error: `Onyx API returned ${onyxRes.status}`, detail: errorText },
        { status: 502 }
      );
    }

    if (!onyxRes.body) {
      return NextResponse.json(
        { error: "No response body from Onyx API" },
        { status: 502 }
      );
    }

    // Convert the Onyx Packet stream to an Anthropic SSE stream so the frontend can parse it identically
    let chatSessionIdToDelete: string | null = null;
    const readable = new ReadableStream({
      async start(controller) {
        const reader = onyxRes.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";

            for (const line of lines) {
              const trimmedLine = line.trim();
              if (!trimmedLine) continue;

              try {
                const packet = JSON.parse(trimmedLine);
                if (packet && packet.obj && packet.obj.type === "message_delta" && packet.obj.content) {
                  const delta = packet.obj.content;
                  const anthropicSse = `data: ${JSON.stringify({ type: "content_block_delta", delta: { text: delta } })}\n\n`;
                  controller.enqueue(new TextEncoder().encode(anthropicSse));
                }

                // Onyx includes chat_session_id in some of the stream packets (e.g. ChatMessageDetail)
                if (packet && packet.chat_session_id && !chatSessionIdToDelete) {
                  chatSessionIdToDelete = packet.chat_session_id;
                }
              } catch {
                // Ignore parse errors from other packets
              }
            }
          }
        } catch (e) {
          console.error("Stream parsing error:", e);
        } finally {
          controller.enqueue(new TextEncoder().encode("data: [DONE]\n\n"));
          controller.close();

          // Clean up the chat session so it doesn't pollute the user's history.
          // Awaited so a failure can be observed; the stream is already closed
          // above so this does not delay the client response. Use minimal
          // cookie-only headers rather than the original POST headers (which
          // carry stale Content-Type/Content-Length and forwarded fields not
          // valid for a DELETE).
          if (chatSessionIdToDelete) {
            const cleanupHeaders = new Headers();
            const cookie = headers.get("cookie");
            if (cookie) cleanupHeaders.set("cookie", cookie);
            try {
              const res = await fetch(
                `${INTERNAL_URL}/delete-chat-session/${chatSessionIdToDelete}`,
                { method: "DELETE", headers: cleanupHeaders }
              );
              if (!res.ok) {
                console.error(
                  `Failed to delete transient agent wizard chat session ${chatSessionIdToDelete}: ${res.status} ${await res.text()}`
                );
              }
            } catch (e) {
              console.error(
                `Failed to delete transient agent wizard chat session ${chatSessionIdToDelete}:`,
                e
              );
            }
          }
        }
      }
    });

    const responseHeaders = new Headers();
    responseHeaders.set("Content-Type", "text/event-stream");
    responseHeaders.set("Cache-Control", "no-cache");
    responseHeaders.set("Connection", "keep-alive");
    // Client expects X-LLM-Provider to be anthropic or openai to know how to parse
    responseHeaders.set("X-LLM-Provider", "anthropic");

    return new Response(readable, {
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
