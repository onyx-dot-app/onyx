"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useFormikContext } from "formik";
import { SvgArrowUp, SvgOnyxOctagon } from "@opal/icons";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChatMessage {
  role: "assistant" | "user";
  content: string;
}

interface AgentBuilderChatProps {
  onFieldsUpdated?: (fieldNames: string[]) => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WELCOME_MESSAGE: ChatMessage = {
  role: "assistant",
  content:
    "Let's build your agent together. Tell me what you'd like it to do — what's its purpose, who will use it, and what should it be great at? I'll fill in the form on the right as we talk.",
};

const FIELDS_START = "<<<FIELDS>>>";
const FIELDS_END = "<<<END>>>";

const FORM_FIELDS = [
  "name",
  "description",
  "instructions",
  "starter_messages",
  "web_search",
  "image_generation",
  "code_interpreter",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Strip any <<<FIELDS>>>...<<<END>>> block from visible text. */
function stripFieldsBlock(text: string): string {
  const startIdx = text.indexOf(FIELDS_START);
  if (startIdx === -1) return text;
  const endIdx = text.indexOf(FIELDS_END, startIdx);
  if (endIdx === -1) {
    return text.slice(0, startIdx).trimEnd();
  }
  return (
    text.slice(0, startIdx) + text.slice(endIdx + FIELDS_END.length)
  ).trimEnd();
}

/** Extract the JSON between <<<FIELDS>>> and <<<END>>>. */
function extractFieldsJson(text: string): Record<string, unknown> | null {
  const startIdx = text.indexOf(FIELDS_START);
  if (startIdx === -1) return null;
  const endIdx = text.indexOf(FIELDS_END, startIdx);
  if (endIdx === -1) return null;
  const jsonStr = text.slice(startIdx + FIELDS_START.length, endIdx).trim();
  try {
    return JSON.parse(jsonStr) as Record<string, unknown>;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function TypingDots() {
  return (
    <div className="flex items-center gap-[3px] py-[2px]">
      <span className="w-[5px] h-[5px] rounded-full bg-text-03 animate-bounce [animation-delay:0ms]" />
      <span className="w-[5px] h-[5px] rounded-full bg-text-03 animate-bounce [animation-delay:150ms]" />
      <span className="w-[5px] h-[5px] rounded-full bg-text-03 animate-bounce [animation-delay:300ms]" />
    </div>
  );
}

interface MessageBubbleProps {
  message: ChatMessage;
  isLastMessage: boolean;
  isStreaming: boolean;
}

function MessageBubble({ message, isLastMessage, isStreaming }: MessageBubbleProps) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] px-3 py-2 rounded-16 bg-background-tint-03 text-sm text-text-04 leading-relaxed whitespace-pre-wrap break-words">
          {message.content}
        </div>
      </div>
    );
  }

  // Assistant message
  return (
    <div className="flex items-start gap-2">
      <div className="flex-shrink-0 w-6 h-6 rounded-full bg-background-tint-02 border border-border-01 flex items-center justify-center mt-0.5">
        <SvgOnyxOctagon className="w-[14px] h-[14px] stroke-text-03" />
      </div>
      <div className="flex-1 min-w-0 text-sm text-text-04 leading-relaxed whitespace-pre-wrap break-words pt-[2px]">
        {message.content || (isStreaming && isLastMessage ? <TypingDots /> : null)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AgentBuilderChat({
  onFieldsUpdated,
}: AgentBuilderChatProps) {
  const { values, setFieldValue } = useFormikContext<Record<string, unknown>>();

  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [noLlm, setNoLlm] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const textareaWrapperRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const wrapper = textareaWrapperRef.current;
    const ta = textareaRef.current;
    if (!wrapper || !ta) return;
    wrapper.style.height = "auto";
    const newH = Math.min(ta.scrollHeight, 120);
    wrapper.style.height = `${newH}px`;
  }, [input]);

  // ------------------------------------------------------------------
  // Send message
  // ------------------------------------------------------------------

  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;

    const userMessage: ChatMessage = { role: "user", content: trimmed };
    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);
    setInput("");
    setIsStreaming(true);

    // Gather current form values to send along
    const currentValues: Record<string, unknown> = {};
    for (const field of FORM_FIELDS) {
      currentValues[field] = values[field];
    }

    // Placeholder for assistant response
    const assistantIdx = updatedMessages.length;
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    let fullText = "";

    try {
      const response = await fetch("/api/agent-wizard-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: updatedMessages.map((m) => ({
            role: m.role,
            content: m.content,
          })),
          currentValues,
        }),
      });

      if (!response.ok) {
        const errorBody = await response.text().catch(() => "Unknown error");
        const isNoProvider =
          response.status === 500 &&
          errorBody.toLowerCase().includes("no llm provider");

        if (isNoProvider) {
          setNoLlm(true);
          setMessages((prev) => {
            const copy = [...prev];
            copy[assistantIdx] = {
              role: "assistant",
              content:
                "No LLM provider is configured yet. You can still fill in the form on the right — it works independently of the chat.",
            };
            return copy;
          });
        } else {
          setMessages((prev) => {
            const copy = [...prev];
            copy[assistantIdx] = {
              role: "assistant",
              content: `Something went wrong (${response.status}). You can still fill in the form directly.`,
            };
            return copy;
          });
        }
        setIsStreaming(false);
        return;
      }

      const provider = response.headers.get("X-LLM-Provider") ?? "";
      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmedLine = line.trim();
          if (!trimmedLine || trimmedLine === "data: [DONE]") continue;
          if (!trimmedLine.startsWith("data: ")) continue;

          const jsonStr = trimmedLine.slice(6);
          let delta = "";

          try {
            const parsed = JSON.parse(jsonStr);

            if (provider === "anthropic") {
              if (
                parsed.type === "content_block_delta" &&
                parsed.delta?.text
              ) {
                delta = parsed.delta.text;
              }
            } else if (provider === "openai") {
              if (parsed.choices?.[0]?.delta?.content) {
                delta = parsed.choices[0].delta.content;
              }
            } else {
              if (parsed.type === "content_block_delta" && parsed.delta?.text) {
                delta = parsed.delta.text;
              } else if (parsed.choices?.[0]?.delta?.content) {
                delta = parsed.choices[0].delta.content;
              }
            }
          } catch {
            // Skip unparseable lines
          }

          if (delta) {
            fullText += delta;
            const displayText = stripFieldsBlock(fullText);
            setMessages((prev) => {
              const copy = [...prev];
              copy[assistantIdx] = {
                role: "assistant",
                content: displayText,
              };
              return copy;
            });
          }
        }
      }

      // Stream complete — final parse for fields
      const fieldsData = extractFieldsJson(fullText);
      const displayText = stripFieldsBlock(fullText);

      setMessages((prev) => {
        const copy = [...prev];
        copy[assistantIdx] = { role: "assistant", content: displayText };
        return copy;
      });

      if (fieldsData) {
        const updatedFieldNames: string[] = [];
        for (const [key, val] of Object.entries(fieldsData)) {
          if (FORM_FIELDS.includes(key)) {
            setFieldValue(key, val);
            updatedFieldNames.push(key);
          }
        }
        if (updatedFieldNames.length > 0) {
          onFieldsUpdated?.(updatedFieldNames);
        }
      }
    } catch {
      setMessages((prev) => {
        const copy = [...prev];
        copy[assistantIdx] = {
          role: "assistant",
          content:
            "Couldn't connect to the AI. You can still fill in the form on the right directly.",
        };
        return copy;
      });
    } finally {
      setIsStreaming(false);
    }
  }, [input, isStreaming, messages, values, setFieldValue, onFieldsUpdated]);

  // ------------------------------------------------------------------
  // Key handler
  // ------------------------------------------------------------------

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey && !(e.nativeEvent as any).isComposing) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-4 pt-4 pb-3 flex-shrink-0 border-b border-border-01">
        <p className="text-[13px] font-semibold text-text-04 leading-none">
          Agent Builder
        </p>
        <p className="text-[12px] text-text-03 mt-1 leading-tight">
          Describe your agent and I&apos;ll configure it for you
        </p>
      </div>

      {/* No LLM banner */}
      {noLlm && (
        <div className="mx-3 mt-3 px-3 py-2 rounded-12 bg-status-warning-00 border border-status-warning-02 flex-shrink-0">
          <p className="text-[12px] text-text-03 leading-snug">
            No LLM provider configured. The form on the right works independently — fill it in directly.
          </p>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4 min-h-0">
        {messages.map((msg, idx) => (
          <MessageBubble
            key={idx}
            message={msg}
            isLastMessage={idx === messages.length - 1}
            isStreaming={isStreaming}
          />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area — styled to match Onyx's AppInputBar */}
      <div className="px-3 pb-3 flex-shrink-0">
        <div className="flex flex-col shadow-01 bg-background-neutral-00 rounded-16">
          {/* Textarea row */}
          <div className="px-3 py-2 flex items-center">
            <div ref={textareaWrapperRef} className="flex-1 min-h-[1.75rem]" style={{ height: "1.75rem" }}>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Describe your agent…"
                disabled={isStreaming || noLlm}
                rows={1}
                className="w-full h-full outline-none bg-transparent resize-none placeholder:text-text-03 text-[13px] text-text-04 whitespace-pre-wrap break-words overflow-y-auto leading-relaxed disabled:opacity-50"
                style={{ scrollbarWidth: "thin" }}
              />
            </div>
          </div>

          {/* Bottom bar with send button */}
          <div className="flex justify-end items-center px-2 pb-2 pt-0">
            <button
              onClick={handleSend}
              disabled={isStreaming || !input.trim() || noLlm}
              className="flex items-center justify-center w-[1.75rem] h-[1.75rem] rounded-full bg-text-04 text-background-neutral-00 disabled:opacity-30 hover:opacity-80 transition-opacity flex-shrink-0"
              aria-label="Send message"
            >
              {isStreaming ? (
                <SimpleLoader className="w-3 h-3 stroke-background-neutral-00" />
              ) : (
                <SvgArrowUp className="w-3 h-3" />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
