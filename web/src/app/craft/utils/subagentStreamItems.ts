"use client";

import {
  StreamItem,
  ToolCallState,
  TodoListState,
} from "../types/displayTypes";
import { parsePacket } from "./parsePacket";
import { genId } from "./streamItemHelpers";

const MAX_SUBAGENT_DEPTH = 3;

function upsertToolCall(
  items: StreamItem[],
  toolCallId: string,
  updates: Partial<ToolCallState>
) {
  const existingIndex = items.findIndex(
    (item) => item.type === "tool_call" && item.toolCall.id === toolCallId
  );

  if (existingIndex >= 0) {
    const existing = items[existingIndex];
    if (existing && existing.type === "tool_call") {
      items[existingIndex] = {
        ...existing,
        toolCall: {
          ...existing.toolCall,
          ...updates,
        },
      };
    }
    return;
  }

  items.push({
    type: "tool_call",
    id: toolCallId,
    toolCall: {
      id: toolCallId,
      kind: updates.kind || "other",
      title: updates.title || "Running tool",
      description: updates.description || "",
      command: updates.command || "",
      status: updates.status || "pending",
      rawOutput: updates.rawOutput || "",
      subagentType: updates.subagentType,
      subagentSessionId: updates.subagentSessionId,
      subagentStreamItems: updates.subagentStreamItems,
      isNewFile: updates.isNewFile ?? true,
      oldContent: updates.oldContent || "",
      newContent: updates.newContent || "",
    },
  });
}

function upsertTodoList(
  items: StreamItem[],
  todoListId: string,
  todoList: TodoListState
) {
  const existingIndex = items.findIndex(
    (item) => item.type === "todo_list" && item.todoList.id === todoListId
  );
  if (existingIndex >= 0) {
    const existing = items[existingIndex];
    if (existing && existing.type === "todo_list") {
      items[existingIndex] = {
        ...existing,
        todoList: {
          ...existing.todoList,
          ...todoList,
        },
      };
    }
    return;
  }

  items.push({
    type: "todo_list",
    id: todoListId,
    todoList,
  });
}

export function convertSubagentPacketDataToStreamItems(
  packetData: Record<string, unknown>[],
  depth = 0
): StreamItem[] {
  if (depth >= MAX_SUBAGENT_DEPTH) {
    return [];
  }

  const items: StreamItem[] = [];

  for (const rawPacket of packetData) {
    const parsed = parsePacket(rawPacket);

    switch (parsed.type) {
      case "text_chunk": {
        if (!parsed.text) break;
        const lastItem = items[items.length - 1];
        if (lastItem && lastItem.type === "text") {
          lastItem.content += parsed.text;
        } else {
          items.push({
            type: "text",
            id: genId("subagent-text"),
            content: parsed.text,
            isStreaming: false,
          });
        }
        break;
      }

      case "thinking_chunk": {
        if (!parsed.text) break;
        const lastItem = items[items.length - 1];
        if (lastItem && lastItem.type === "thinking") {
          lastItem.content += parsed.text;
        } else {
          items.push({
            type: "thinking",
            id: genId("subagent-thinking"),
            content: parsed.text,
            isStreaming: false,
          });
        }
        break;
      }

      case "tool_call_start": {
        if (parsed.isTodo) break;
        upsertToolCall(items, parsed.toolCallId, {
          id: parsed.toolCallId,
          kind: parsed.kind,
          status: "pending",
          title: "",
          description: "",
          command: "",
          rawOutput: "",
        });
        break;
      }

      case "tool_call_progress": {
        if (parsed.isTodo) {
          upsertTodoList(items, parsed.toolCallId, {
            id: parsed.toolCallId,
            todos: parsed.todos,
            isOpen: false,
          });
          break;
        }

        upsertToolCall(items, parsed.toolCallId, {
          id: parsed.toolCallId,
          kind: parsed.kind,
          status: parsed.status,
          title: parsed.title,
          description: parsed.description,
          command: parsed.command,
          rawOutput: parsed.rawOutput,
          subagentType: parsed.subagentType ?? undefined,
          subagentSessionId: parsed.subagentSessionId ?? undefined,
          subagentStreamItems:
            parsed.subagentPacketData.length > 0
              ? convertSubagentPacketDataToStreamItems(
                  parsed.subagentPacketData,
                  depth + 1
                )
              : undefined,
          isNewFile: parsed.isNewFile,
          oldContent: parsed.oldContent,
          newContent: parsed.newContent,
        });
        break;
      }

      case "subagent_packet":
      case "prompt_response":
      case "artifact_created":
      case "error":
      case "unknown":
      default:
        break;
    }
  }

  return items;
}
