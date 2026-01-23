# Plan: Rendering Todo List Items in Build Chat Panel

## System Analysis

### How SSE Packets Flow (End-to-End)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ OPENCODE AGENT (in Sandbox)                                                 │
│   - Calls TodoWrite tool with todos array                                   │
│   - Emits ACP events: ToolCallStart → ToolCallProgress (multiple)           │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │ JSON-RPC stdout
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ BACKEND: SandboxManager.send_message()                                      │
│   - Parses ACP events from agent stdout                                     │
│   - Yields typed objects (ToolCallStart, ToolCallProgress, etc.)            │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ BACKEND: SessionManager._stream_cli_agent_response()                        │
│   File: backend/onyx/server/features/build/session/manager.py               │
│                                                                             │
│   - For each ACP event:                                                     │
│     - ToolCallStart → Yield SSE (NOT saved to DB)                           │
│     - ToolCallProgress → Yield SSE; Save to DB if status="completed"        │
│   - Serializes to SSE format: "event: message\ndata: {JSON}\n\n"            │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │ SSE Stream (text/event-stream)
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ FRONTEND: processSSEStream()                                                │
│   File: web/src/app/build/services/apiServices.ts                           │
│                                                                             │
│   - Parses SSE lines, extracts JSON data                                    │
│   - Calls onPacket(packet) for each parsed packet                           │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ FRONTEND: useBuildStreaming.streamMessage()                                 │
│   File: web/src/app/build/hooks/useBuildStreaming.ts                        │
│                                                                             │
│   - Switch on packet.type:                                                  │
│     - "agent_message_chunk" → Create/update text StreamItem                 │
│     - "agent_thought_chunk" → Create/update thinking StreamItem             │
│     - "tool_call_start" → Create tool_call StreamItem                       │
│     - "tool_call_progress" → Update tool_call StreamItem                    │
│   - Appends StreamItems to Zustand store in FIFO order                      │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ FRONTEND: BuildMessageList → ToolCallPill                                   │
│   Files: web/src/app/build/components/BuildMessageList.tsx                  │
│          web/src/app/build/components/ToolCallPill.tsx                      │
│                                                                             │
│   - Renders streamItems in order                                            │
│   - tool_call items rendered as ToolCallPill (expandable card)              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Current Data Structures

#### StreamItem Types (displayTypes.ts)
```typescript
export type StreamItem =
  | { type: "text"; id: string; content: string; isStreaming: boolean }
  | { type: "thinking"; id: string; content: string; isStreaming: boolean }
  | { type: "tool_call"; id: string; toolCall: ToolCallState };
```

#### ToolCallState (displayTypes.ts)
```typescript
export interface ToolCallState {
  id: string;
  kind: ToolCallKind;           // "execute" | "read" | "task" | "other"
  title: string;                 // "Running command", "Writing file", etc.
  description: string;           // File path or command description
  command: string;               // Actual command or file path
  status: ToolCallStatus;        // "pending" | "in_progress" | "completed" | "failed"
  rawOutput: string;             // Full output for expanded view
  subagentType?: string;         // For task tool calls
}
```

### TodoWrite Packet Structure (Expected from OpenCode)

Based on the ACP protocol and OpenCode tool definitions:

```json
// tool_call_start
{
  "type": "tool_call_start",
  "tool_call_id": "toolu_xyz123",
  "kind": "other",
  "title": "todowrite",
  "raw_input": {
    "todos": [
      { "content": "Create API endpoint", "status": "pending", "activeForm": "Creating API endpoint" },
      { "content": "Write tests", "status": "pending", "activeForm": "Writing tests" }
    ]
  },
  "status": "pending"
}

// tool_call_progress (updates as agent works)
{
  "type": "tool_call_progress",
  "tool_call_id": "toolu_xyz123",
  "kind": "other",
  "title": "todowrite",
  "raw_input": {
    "todos": [
      { "content": "Create API endpoint", "status": "completed", "activeForm": "Creating API endpoint" },
      { "content": "Write tests", "status": "in_progress", "activeForm": "Writing tests" }
    ]
  },
  "status": "completed"
}
```

---

## Implementation Plan

### Goal

Render todo list items in the chat panel with:
1. **FIFO rendering**: Multiple todo list cards can appear in sequence in the AI message
2. **Auto-collapse**: When a new todo list appears, previous ones collapse; final one stays open
3. **Persistence**: Save todo packets to DB for re-rendering on refresh

---

### Phase 1: Frontend - New StreamItem Type & Component

#### 1.1 Add `todo_list` StreamItem Type

**File**: `web/src/app/build/types/displayTypes.ts`

```typescript
// Add new types
export type TodoStatus = "pending" | "in_progress" | "completed";

export interface TodoItem {
  content: string;          // The task description
  status: TodoStatus;       // Current status
  activeForm: string;       // Present tense form (e.g., "Creating API endpoint")
}

export interface TodoListState {
  id: string;               // Tool call ID
  todos: TodoItem[];        // Array of todo items
  isOpen: boolean;          // Whether the card is expanded (for UI state only)
}

// Update StreamItem union
export type StreamItem =
  | { type: "text"; id: string; content: string; isStreaming: boolean }
  | { type: "thinking"; id: string; content: string; isStreaming: boolean }
  | { type: "tool_call"; id: string; toolCall: ToolCallState }
  | { type: "todo_list"; id: string; todoList: TodoListState };
```

#### 1.2 Create TodoListCard Component

**File**: `web/src/app/build/components/TodoListCard.tsx`

```typescript
interface TodoListCardProps {
  todoList: TodoListState;
  defaultOpen?: boolean;
}

export default function TodoListCard({ todoList, defaultOpen = true }: TodoListCardProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  // Calculate progress stats
  const total = todoList.todos.length;
  const completed = todoList.todos.filter(t => t.status === "completed").length;
  const inProgress = todoList.todos.filter(t => t.status === "in_progress").length;

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <div className="border rounded-lg overflow-hidden bg-background-neutral-01 border-border-02">
        <CollapsibleTrigger asChild>
          <button className="w-full flex items-center justify-between px-3 py-2 hover:bg-background-tint-02">
            <div className="flex items-center gap-2">
              <SvgChecklist className="size-4 stroke-text-03" />
              <span className="text-sm font-medium text-text-04">Tasks</span>
              <span className="text-xs text-text-03">
                {completed}/{total} completed
              </span>
            </div>
            {inProgress > 0 && (
              <SvgLoader className="size-4 stroke-status-info-05 animate-spin" />
            )}
            <SvgChevronDown className={cn(
              "size-4 stroke-text-03 transition-transform",
              !isOpen && "rotate-[-90deg]"
            )} />
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="px-3 pb-3 space-y-1">
            {todoList.todos.map((todo, index) => (
              <TodoItemRow key={index} todo={todo} />
            ))}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}

function TodoItemRow({ todo }: { todo: TodoItem }) {
  return (
    <div className="flex items-start gap-2 py-1">
      {/* Status indicator */}
      {todo.status === "completed" ? (
        <SvgCheckCircle className="size-4 stroke-status-success-05 mt-0.5 shrink-0" />
      ) : todo.status === "in_progress" ? (
        <SvgLoader className="size-4 stroke-status-info-05 animate-spin mt-0.5 shrink-0" />
      ) : (
        <div className="size-4 rounded-full border-2 border-text-03 mt-0.5 shrink-0" />
      )}

      {/* Task text */}
      <span className={cn(
        "text-sm",
        todo.status === "completed" ? "text-text-03 line-through" : "text-text-04"
      )}>
        {todo.status === "in_progress" ? todo.activeForm : todo.content}
      </span>
    </div>
  );
}
```

---

### Phase 2: Frontend - Streaming Hook Updates

#### 2.1 Handle TodoWrite in useBuildStreaming

**File**: `web/src/app/build/hooks/useBuildStreaming.ts`

```typescript
// Add helper function to detect TodoWrite tool
function isTodoWriteTool(packet: Record<string, unknown>): boolean {
  const toolName = (
    (packet.tool_name || packet.toolName || packet.title) as string | undefined
  )?.toLowerCase();
  return toolName === "todowrite" || toolName === "todo_write";
}

// Add helper to extract todos from packet
function extractTodos(packet: Record<string, unknown>): TodoItem[] {
  const rawInput = (packet.raw_input || packet.rawInput) as Record<string, unknown> | null;
  if (!rawInput?.todos || !Array.isArray(rawInput.todos)) return [];

  return rawInput.todos.map((t: any) => ({
    content: t.content || "",
    status: normalizeTodoStatus(t.status),
    activeForm: t.activeForm || t.content || "",
  }));
}

// In streamMessage callback, update switch statement:
case "tool_call_start": {
  // Check if this is a TodoWrite call
  if (isTodoWriteTool(packetData)) {
    // Collapse any previous todo lists
    collapseAllTodoLists(sessionId);

    // Create new todo_list StreamItem (open by default)
    const toolCallId = (packetData.tool_call_id || packetData.toolCallId || genId("todo")) as string;
    const todos = extractTodos(packetData);

    const item: StreamItem = {
      type: "todo_list",
      id: toolCallId,
      todoList: {
        id: toolCallId,
        todos,
        isOpen: true,
      },
    };
    appendStreamItem(sessionId, item);
    lastItemType = "tool"; // Still track as tool for finalization
    break;
  }

  // ... existing tool_call_start handling ...
}

case "tool_call_progress": {
  // Check if this is a TodoWrite update
  if (isTodoWriteTool(packetData)) {
    const toolCallId = (packetData.tool_call_id || packetData.toolCallId) as string;
    const todos = extractTodos(packetData);

    updateTodoListStreamItem(sessionId, toolCallId, { todos });
    break;
  }

  // ... existing tool_call_progress handling ...
}
```

#### 2.2 Add Store Actions for Todo Lists

**File**: `web/src/app/build/hooks/useBuildSessionStore.ts`

```typescript
// Add to interface BuildSessionStore:
updateTodoListStreamItem: (
  sessionId: string,
  todoListId: string,
  updates: Partial<TodoListState>
) => void;
collapseAllTodoLists: (sessionId: string) => void;

// Add implementations:
updateTodoListStreamItem: (sessionId, todoListId, updates) => {
  set((state) => {
    const session = state.sessions.get(sessionId);
    if (!session) return state;

    const streamItems = session.streamItems.map((item) => {
      if (item.type === "todo_list" && item.todoList.id === todoListId) {
        return {
          ...item,
          todoList: { ...item.todoList, ...updates },
        };
      }
      return item;
    }) as StreamItem[];

    const newSessions = new Map(state.sessions);
    newSessions.set(sessionId, { ...session, streamItems, lastAccessed: new Date() });
    return { sessions: newSessions };
  });
},

collapseAllTodoLists: (sessionId) => {
  set((state) => {
    const session = state.sessions.get(sessionId);
    if (!session) return state;

    const streamItems = session.streamItems.map((item) => {
      if (item.type === "todo_list") {
        return {
          ...item,
          todoList: { ...item.todoList, isOpen: false },
        };
      }
      return item;
    }) as StreamItem[];

    const newSessions = new Map(state.sessions);
    newSessions.set(sessionId, { ...session, streamItems, lastAccessed: new Date() });
    return { sessions: newSessions };
  });
},
```

---

### Phase 3: Backend - Persist Todo Packets

#### 3.1 Save TodoWrite Progress to DB

**File**: `backend/onyx/server/features/build/session/manager.py`

In `_stream_cli_agent_response()`, update the `ToolCallProgress` handling:

```python
elif isinstance(acp_event, ToolCallProgress):
    event_data = acp_event.model_dump(mode="json", by_alias=True, exclude_none=False)
    event_data["type"] = "tool_call_progress"
    event_data["timestamp"] = datetime.now(tz=timezone.utc).isoformat()

    # Check if this is a TodoWrite tool call
    tool_name = (event_data.get("title") or "").lower()
    is_todo_write = tool_name in ("todowrite", "todo_write")

    # Save to DB:
    # - For TodoWrite: Save every progress update (todos change frequently)
    # - For other tools: Only save when status="completed"
    if is_todo_write or acp_event.status == "completed":
        create_message(
            session_id=session_id,
            message_type=MessageType.ASSISTANT,
            turn_index=state.turn_index,
            message_metadata=event_data,
            db_session=self._db_session,
        )

    packet_logger.log("tool_call_progress", event_data)
    yield _serialize_acp_event(acp_event, "tool_call_progress")
```

**Note**: For TodoWrite, we save every progress update because the todo items change incrementally. This ensures we capture the final state for rendering on refresh.

---

### Phase 4: Frontend - Load Todos from DB

#### 4.1 Update convertMessagesToStreamItems

**File**: `web/src/app/build/hooks/useBuildSessionStore.ts`

```typescript
function convertMessagesToStreamItems(messages: BuildMessage[]): StreamItem[] {
  const streamItems: StreamItem[] = [];

  // Track the latest todo list state per tool_call_id (for deduplication)
  const todoListMap = new Map<string, TodoListState>();

  for (const message of messages) {
    if (message.type === "user") continue;

    const metadata = message.message_metadata;
    if (!metadata || typeof metadata !== "object") continue;

    const packetType = metadata.type as string;

    switch (packetType) {
      // ... existing cases ...

      case "tool_call_progress": {
        const toolName = ((metadata.title as string) || "").toLowerCase();

        // Handle TodoWrite separately
        if (toolName === "todowrite" || toolName === "todo_write") {
          const toolCallId = (metadata.tool_call_id || metadata.toolCallId || message.id) as string;
          const todos = extractTodosFromMetadata(metadata);

          // Update or create in map (keeps latest state only)
          todoListMap.set(toolCallId, {
            id: toolCallId,
            todos,
            isOpen: false, // Default to collapsed when loaded from history
          });
          break;
        }

        // ... existing tool_call_progress handling ...
      }
    }
  }

  // Add deduplicated todo lists to stream items
  // Insert them in the order they first appeared (approximated by message order)
  for (const [id, todoList] of todoListMap) {
    streamItems.push({
      type: "todo_list",
      id,
      todoList,
    });
  }

  // Note: This simplified approach puts all todo lists at the end.
  // For proper ordering, we'd need to track insertion positions.
  // This is acceptable for MVP since todo lists typically appear
  // interleaved with other content during streaming.

  return streamItems;
}

function extractTodosFromMetadata(metadata: Record<string, any>): TodoItem[] {
  const rawInput = (metadata.raw_input || metadata.rawInput);
  if (!rawInput?.todos || !Array.isArray(rawInput.todos)) return [];

  return rawInput.todos.map((t: any) => ({
    content: t.content || "",
    status: (t.status as TodoStatus) || "pending",
    activeForm: t.activeForm || t.content || "",
  }));
}
```

---

### Phase 5: Frontend - Render in BuildMessageList

#### 5.1 Update BuildMessageList

**File**: `web/src/app/build/components/BuildMessageList.tsx`

```typescript
import TodoListCard from "@/app/build/components/TodoListCard";

// In the streamItems.map() switch:
case "todo_list":
  return (
    <TodoListCard
      key={item.id}
      todoList={item.todoList}
      defaultOpen={item.todoList.isOpen}
    />
  );
```

---

## File Changes Summary

| File | Changes |
|------|---------|
| `web/src/app/build/types/displayTypes.ts` | Add `TodoItem`, `TodoListState`, update `StreamItem` union |
| `web/src/app/build/components/TodoListCard.tsx` | **NEW** - Collapsible todo list component |
| `web/src/app/build/hooks/useBuildStreaming.ts` | Handle `todowrite` tool calls specially |
| `web/src/app/build/hooks/useBuildSessionStore.ts` | Add `updateTodoListStreamItem`, `collapseAllTodoLists`, update `convertMessagesToStreamItems` |
| `web/src/app/build/components/BuildMessageList.tsx` | Render `todo_list` StreamItem type |
| `backend/onyx/server/features/build/session/manager.py` | Save TodoWrite progress packets to DB |

---

## Acceptance Criteria

1. **Streaming Rendering**:
   - When agent calls TodoWrite, a todo list card appears in the chat
   - Todo items show with status indicators (checkbox, spinner, checkmark)
   - Items update in real-time as agent marks them complete

2. **FIFO / Multiple Lists**:
   - Multiple todo list cards can appear in a single response
   - When a new todo list appears, previous ones auto-collapse
   - Final todo list remains open

3. **Persistence**:
   - On page refresh, todo lists are re-rendered from DB
   - All todo items preserve their final state
   - Todo lists default to collapsed when loaded from history

4. **UI Polish**:
   - Shows progress count (e.g., "3/5 completed")
   - Spinner animates on in-progress items
   - Completed items have strikethrough styling
