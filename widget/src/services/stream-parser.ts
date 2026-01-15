/**
 * Stream Parser - Processes SSE packets and updates state
 */

import { Packet, Message } from "@/types/api-types";
import { ChatMessage } from "@/types/widget-types";

export interface ParsedMessage {
  message: ChatMessage;
  isComplete: boolean;
  citations?: any[];
}

/**
 * Process a single packet from the SSE stream
 * Returns the current message being built and any state updates
 */
export function processPacket(
  packet: Packet,
  currentMessage: ChatMessage | null,
): { message: ChatMessage | null; citations?: any[]; status?: string } {
  // Safety check - skip if packet.obj is undefined
  if (!packet || !packet.obj) {
    console.warn("Received malformed packet:", packet);
    return { message: currentMessage };
  }

  const obj = packet.obj;

  switch (obj.type) {
    case "message_start":
      // Start of a new assistant response
      return {
        message: {
          id: `msg-${Date.now()}`,
          role: "assistant",
          content: "",
          timestamp: Date.now(),
          isStreaming: true,
        },
        status: "", // Clear status when response starts
      };

    case "message_delta":
      // Append to current message
      if (currentMessage && currentMessage.role === "assistant") {
        return {
          message: {
            ...currentMessage,
            content: currentMessage.content + (obj.content || ""),
          },
          // No status update - let the message speak for itself
        };
      }
      return { message: currentMessage };

    case "citation_info":
      // Handle citations
      if (currentMessage) {
        return {
          message: currentMessage,
          citations: obj.citations,
        };
      }
      return { message: currentMessage };

    case "search_tool_start":
      // Tool is starting - check if it's internet search
      const isInternetSearch = (obj as any).is_internet_search;
      return {
        message: currentMessage,
        status: isInternetSearch
          ? "Searching the web..."
          : "Searching internally...",
      };

    case "search_tool_queries_delta":
      // Queries being generated
      return {
        message: currentMessage,
        status: "Generating search queries...",
      };

    case "search_tool_documents_delta":
      // Search results coming in
      return {
        message: currentMessage,
        status: "Reading documents...",
      };

    case "open_url_start":
      return {
        message: currentMessage,
        status: "Opening URLs...",
      };

    case "open_url_urls":
      return {
        message: currentMessage,
        status: "Fetching web pages...",
      };

    case "open_url_documents":
      return {
        message: currentMessage,
        status: "Processing web content...",
      };

    case "image_generation_start":
      return {
        message: currentMessage,
        status: "Generating image...",
      };

    case "image_generation_heartbeat":
      return {
        message: currentMessage,
        status: "Generating image...",
      };

    case "python_tool_start":
      return {
        message: currentMessage,
        status: "Running Python code...",
      };

    case "python_tool_delta":
      return {
        message: currentMessage,
        status: "Running Python code...",
      };

    case "custom_tool_start":
      return {
        message: currentMessage,
        status: "Running custom tool...",
      };

    case "reasoning_start":
      return {
        message: currentMessage,
        status: "Thinking...",
      };

    case "reasoning_delta":
      return {
        message: currentMessage,
        status: "Thinking...",
      };

    case "deep_research_plan_start":
      return {
        message: currentMessage,
        status: "Planning research...",
      };

    case "research_agent_start":
      return {
        message: currentMessage,
        status: "Researching...",
      };

    case "intermediate_report_start":
      return {
        message: currentMessage,
        status: "Generating report...",
      };

    case "stop":
    case "overall_stop":
      // End of stream - mark message as complete
      if (currentMessage) {
        return {
          message: {
            ...currentMessage,
            isStreaming: false,
          },
        };
      }
      return { message: currentMessage };

    case "error":
      // Error occurred during streaming
      console.error("Stream error:", obj.exception);
      return { message: currentMessage };

    default:
      // Unknown packet type
      return { message: currentMessage };
  }
}

/**
 * Convert API Message type to widget ChatMessage
 */
export function convertMessage(msg: Message): ChatMessage {
  return {
    id: msg.id,
    role: msg.role,
    content: msg.content,
    timestamp: msg.timestamp,
    isStreaming: msg.isStreaming,
  };
}

/**
 * Check if a packet is the final packet in a stream
 */
export function isStreamComplete(packet: Packet): boolean {
  return packet.obj.type === "overall_stop";
}

/**
 * Check if a packet is an error
 */
export function isStreamError(packet: Packet): boolean {
  return packet.obj.type === "error";
}
