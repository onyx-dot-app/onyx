import { CitationInfo, Packet, SearchDocument } from "@/types/api-types";
import { ChatMessage } from "@/types/widget-types";

interface ParsedPacket {
  message: ChatMessage | null;
  citations?: CitationInfo[];
  documents?: SearchDocument[];
  status?: string;
  messageIds?: { userMessageId: number | null; assistantMessageId: number };
}

/** Track the root answer while tools and child agents publish independent items. */
export class ChatStreamParser {
  private answerMessageId: string | undefined;

  process(packet: Packet, message: ChatMessage | null): ParsedPacket {
    if (packet.error) throw new Error(packet.error);
    if (packet.reserved_assistant_message_id !== undefined) {
      return {
        message,
        messageIds: {
          userMessageId: packet.user_message_id ?? null,
          assistantMessageId: packet.reserved_assistant_message_id,
        },
      };
    }
    const obj = packet.obj;
    if (!obj || packet.identity?.parent_run_id) return { message };
    if (obj.type === "stop") {
      return {
        message: message ? { ...message, isStreaming: false } : null,
        status: "",
      };
    }
    if (obj.type === "item_update") {
      const item = obj.item;
      if (item.kind === "text") {
        if (item.purpose !== "answer") {
          if (this.answerMessageId === packet.identity?.message_id) {
            this.answerMessageId = undefined;
            return {
              message: message ? { ...message, content: "" } : null,
              citations: [],
            };
          }
          return {
            message,
            status:
              item.purpose === "plan" ? "Planning research..." : undefined,
          };
        }
        this.answerMessageId = packet.identity?.message_id;
        return {
          message: {
            ...(message ?? {
              id: `msg-${Date.now()}`,
              role: "assistant",
              timestamp: Date.now(),
            }),
            content: item.text,
            isStreaming: true,
          },
          citations: item.citations,
          documents: item.documents,
          status: "",
        };
      }
      if (item.kind === "reasoning")
        return {
          message,
          status: item.status === "running" ? "Thinking..." : "",
        };
      const status =
        item.status === "pending" || item.status === "running"
          ? ({
              internal_search: "Searching internally...",
              web_search: "Searching the web...",
              open_url: "Opening URLs...",
              generate_image: "Generating image...",
              run_python: "Running Python code...",
              research_agent: "Researching...",
            }[item.name] ?? "Running tool...")
          : "";
      return {
        message,
        status,
        documents:
          item.metadata?.type === "search_result"
            ? (item.metadata.displayed_docs ?? item.metadata.search_docs)
            : undefined,
      };
    }
    if (obj.type === "item_delta") {
      const delta = obj.delta;
      if (
        delta.kind === "text" &&
        packet.identity?.part_id === "answer" &&
        packet.identity.message_id === this.answerMessageId &&
        message
      ) {
        return {
          message: { ...message, content: message.content + delta.text },
        };
      }
      if (
        delta.kind === "tool_output" &&
        delta.metadata?.type === "search_result"
      ) {
        return {
          message,
          documents:
            delta.metadata.displayed_docs ?? delta.metadata.search_docs,
        };
      }
    }
    return { message };
  }
}
