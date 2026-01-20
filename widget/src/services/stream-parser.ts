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

export interface MessageIDs {
  userMessageId: number | null;
  assistantMessageId: number;
}

/**
 * Process a single packet from the SSE stream
 * Returns the current message being built and any state updates
 */
export function processPacket(
  packet: Packet,
  currentMessage: ChatMessage | null,
): {
  message: ChatMessage | null;
  citations?: any[];
  status?: string;
  messageIds?: MessageIDs;
} {
  // Safety check - throw on malformed packets to fail fast
  if (!packet || !packet.obj) {
    throw new Error("Received malformed packet: packet.obj is missing");
  }

  const obj = packet.obj;

  // Handle MessageResponseIDInfo (doesn't have a type field)
  if ("reserved_assistant_message_id" in obj && "user_message_id" in obj) {
    return {
      message: currentMessage,
      messageIds: {
        userMessageId: obj.user_message_id,
        assistantMessageId: obj.reserved_assistant_message_id,
      },
    };
  }

  // Type guard - ensure obj has a type field
  if (!("type" in obj)) {
    throw new Error("Packet missing type field");
  }

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
      return {
        message: currentMessage,
        status: obj.is_internet_search
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
      // Error occurred during streaming - throw to fail fast
      throw new Error(`Stream error: ${obj.exception}`);

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
  return "type" in packet.obj && packet.obj.type === "overall_stop";
}

/**
 * Check if a packet is an error
 */
export function isStreamError(packet: Packet): boolean {
  return "type" in packet.obj && packet.obj.type === "error";
}
