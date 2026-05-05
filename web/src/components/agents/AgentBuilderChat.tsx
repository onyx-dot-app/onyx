"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useFormikContext } from "formik";
import { SvgArrowUp } from "@opal/icons";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { SparklesIcon } from "lucide-react";

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
    "Hi there! Let's build your AI Agent together. Tell me what you'd like it to do — what's its purpose, who will use it, and what should it be great at? I'll automatically fill in the configuration on the right as we talk.",
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
    <div className="flex items-center gap-[4px] py-[4px] px-1">
      <span className="w-[6px] h-[6px] rounded-full bg-blue-500/60 animate-bounce [animation-delay:0ms]" />
      <span className="w-[6px] h-[6px] rounded-full bg-purple-500/60 animate-bounce [animation-delay:150ms]" />
      <span className="w-[6px] h-[6px] rounded-full bg-pink-500/60 animate-bounce [animation-delay:300ms]" />
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
      <div className="flex justify-end mb-6 animate-in slide-in-from-bottom-2 fade-in duration-300">
        <div className="max-w-[85%] px-4 py-3 rounded-2xl rounded-tr-sm bg-gradient-to-br from-indigo-500 to-purple-600 text-[14px] text-white leading-relaxed shadow-md whitespace-pre-wrap break-words">
          {message.content}
        </div>
      </div>
    );
  }

  // Assistant message
  return (
    <div className="flex items-start gap-3 mb-6 animate-in slide-in-from-bottom-2 fade-in duration-300">
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gradient-to-tr from-blue-100 to-indigo-100 border border-indigo-200/50 flex items-center justify-center shadow-sm">
        <SparklesIcon className="w-4 h-4 text-indigo-500" />
      </div>
      <div className="flex-1 min-w-0 text-[14px] text-gray-800 leading-relaxed whitespace-pre-wrap break-words pt-[5px]">
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
  const { values, setFieldValue, setValues } = useFormikContext<Record<string, unknown>>();

  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [noLlm, setNoLlm] = useState(false);
  const [isFocused, setIsFocused] = useState(false);

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const textareaWrapperRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom without scrolling the whole page
  useEffect(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
    }
  }, [messages, isStreaming]);

  // Auto-resize textarea
  useEffect(() => {
    const wrapper = textareaWrapperRef.current;
    const ta = textareaRef.current;
    if (!wrapper || !ta) return;
    wrapper.style.height = "auto";
    const newH = Math.min(ta.scrollHeight, 120);
    wrapper.style.height = `${newH}px`;
  }, [input]);

  // Send message
  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;

    const userMessage: ChatMessage = { role: "user", content: trimmed };
    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);
    setInput("");
    setIsStreaming(true);

    const currentValues: Record<string, unknown> = {};
    for (const field of FORM_FIELDS) {
      currentValues[field] = values[field];
    }

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
                "No AI models are configured yet. You can still fill in the form on the right — it works perfectly without the chat.",
            };
            return copy;
          });
        } else {
          setMessages((prev) => {
            const copy = [...prev];
            copy[assistantIdx] = {
              role: "assistant",
              content: `Oops! Something went wrong (${response.status}). Feel free to adjust the form directly.`,
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

      // Final parse
      const fieldsData = extractFieldsJson(fullText);
      const displayText = stripFieldsBlock(fullText);

      setMessages((prev) => {
        const copy = [...prev];
        copy[assistantIdx] = { role: "assistant", content: displayText };
        return copy;
      });

      if (fieldsData) {
        const updatedFieldNames: string[] = [];
        const newValues = { ...values };
        
        for (const [key, val] of Object.entries(fieldsData)) {
          if (FORM_FIELDS.includes(key)) {
            newValues[key] = val;
            updatedFieldNames.push(key);
          }
        }
        if (updatedFieldNames.length > 0) {
          setValues(newValues, true);
          onFieldsUpdated?.(updatedFieldNames);
        }
      }
    } catch {
      setMessages((prev) => {
        const copy = [...prev];
        copy[assistantIdx] = {
          role: "assistant",
          content:
            "I'm having trouble connecting to the backend. You can manually configure your agent on the right.",
        };
        return copy;
      });
    } finally {
      setIsStreaming(false);
    }
  }, [input, isStreaming, messages, values, setFieldValue, onFieldsUpdated]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey && !(e.nativeEvent as any).isComposing) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden bg-[#FAFAFA] relative">
      {/* Decorative background gradients */}
      <div className="absolute top-[-10%] left-[-10%] w-[120%] h-[40%] bg-gradient-to-br from-indigo-100/40 via-purple-100/30 to-transparent blur-3xl pointer-events-none" />
      
      {/* Header */}
      <div className="relative px-6 pt-6 pb-4 flex-shrink-0 border-b border-gray-200/50 bg-white/50 backdrop-blur-sm z-10">
        <h2 className="text-[16px] font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-600 to-purple-600 tracking-tight">
          AI Co-Pilot
        </h2>
        <p className="text-[13px] text-gray-500 mt-1">
          Chat with me to instantly configure your agent
        </p>
      </div>

      {/* Messages Area */}
      <div 
        ref={scrollContainerRef}
        className="relative flex-1 overflow-y-auto px-6 py-6 flex flex-col z-10 scrollbar-thin scrollbar-thumb-gray-200 scrollbar-track-transparent"
      >
        {noLlm && (
          <div className="mb-6 p-4 rounded-xl bg-orange-50 border border-orange-200 shadow-sm animate-in fade-in">
            <p className="text-[13px] text-orange-800 font-medium">
              No AI models configured.
            </p>
            <p className="text-[12px] text-orange-600 mt-1">
              The wizard is offline, but you can build your agent using the form on the right.
            </p>
          </div>
        )}

        {messages.map((msg, idx) => (
          <MessageBubble
            key={idx}
            message={msg}
            isLastMessage={idx === messages.length - 1}
            isStreaming={isStreaming}
          />
        ))}
      </div>

      {/* Input Area */}
      <div className="relative p-4 pt-0 bg-gradient-to-t from-[#FAFAFA] via-[#FAFAFA] to-transparent z-20 flex-shrink-0">
        <div 
          className={`flex flex-col bg-white border rounded-2xl shadow-sm transition-all duration-300 ${
            isFocused 
              ? "border-indigo-300 ring-4 ring-indigo-50 shadow-indigo-100/50" 
              : "border-gray-200 hover:border-gray-300"
          }`}
        >
          <div className="px-4 py-3 flex items-center">
            <div ref={textareaWrapperRef} className="flex-1 min-h-[22px]" style={{ height: "22px" }}>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                onFocus={() => setIsFocused(true)}
                onBlur={() => setIsFocused(false)}
                placeholder="Message Co-Pilot..."
                disabled={isStreaming || noLlm}
                rows={1}
                className="w-full h-full outline-none bg-transparent resize-none text-[14px] text-gray-800 placeholder:text-gray-400 whitespace-pre-wrap break-words overflow-y-auto leading-relaxed disabled:opacity-50"
                style={{ scrollbarWidth: "thin" }}
              />
            </div>
          </div>

          <div className="flex justify-end px-3 pb-3">
            <button
              onClick={handleSend}
              disabled={isStreaming || !input.trim() || noLlm}
              className={`flex items-center justify-center w-8 h-8 rounded-full transition-all duration-200 flex-shrink-0 ${
                isStreaming || !input.trim() || noLlm
                  ? "bg-gray-100 text-gray-400"
                  : "bg-indigo-600 text-white hover:bg-indigo-700 shadow-md hover:shadow-lg hover:-translate-y-[1px]"
              }`}
              aria-label="Send message"
            >
              {isStreaming ? (
                <SimpleLoader className="w-4 h-4 stroke-gray-400" />
              ) : (
                <SvgArrowUp className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>
        <div className="text-center mt-2">
          <p className="text-[11px] text-gray-400">
            Co-Pilot can make mistakes. Verify the agent configuration.
          </p>
        </div>
      </div>
    </div>
  );
}
