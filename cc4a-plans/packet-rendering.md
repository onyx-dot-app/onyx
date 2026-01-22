# Build Mode Packet Rendering Plan

Rewrite the packet rendering system in Build mode chat panel to render all packets chronologically.

## What's Being Replaced

```
AIMessageWithTools → BuildAgentTimeline → BuildToolCallRenderer
```

**Problems**: Grouped timeline instead of chronological, misaligned packet types, no thinking display.

## New Architecture

```
BuildAIResponse
├── TextChunk          (agent_message_chunk → markdown)
├── ThinkingCard       (agent_thought_chunk → expandable card)
└── ToolCallPill       (tool_call_start/progress → expandable pill)
```

**Principles**:
- All packets rendered chronologically as they arrive
- Adjacent text/thinking chunks merge into single blocks
- Tool calls as full-width expandable pills with raw output

---

## Types

### Packet Types (from backend)

```typescript
interface AgentMessageChunkPacket {
  type: "agent_message_chunk";
  content: { type: "text"; text: string };
}

interface AgentThoughtChunkPacket {
  type: "agent_thought_chunk";
  content: { type: "text"; text: string };
}

interface ToolCallStartPacket {
  type: "tool_call_start";
  toolCallId: string;
  title: string;                          // "bash", "read", "apply_patch"
  kind: "execute" | "read" | "other";
  status: "pending";
}

interface ToolCallProgressPacket {
  type: "tool_call_progress";
  toolCallId: string;
  kind: "execute" | "read" | "other";
  status: "pending" | "in_progress" | "completed" | "failed";
  rawInput: { command?: string; description?: string; filePath?: string } | null;
  rawOutput: { output?: string; metadata?: { output?: string; diff?: string } } | null;
}

interface PromptResponsePacket {
  type: "prompt_response";
  stopReason: "end_turn";
}

interface ErrorPacket {
  type: "error";
  message: string;
}
```

### Display Types

```typescript
type DisplayItem =
  | { type: "text"; content: string }
  | { type: "thinking"; content: string; isStreaming: boolean }
  | { type: "tool_call"; toolCall: ToolCallState };

interface ToolCallState {
  id: string;
  kind: "execute" | "read" | "other";
  title: string;
  description: string;     // "Listing output directory"
  command: string;         // "ls outputs/"
  status: "pending" | "in_progress" | "completed" | "failed";
  rawOutput: string;       // Full output for expanded view
}
```

---

## Components

### TextChunk
Renders markdown using `MinimalMarkdown` (same as main chat).

### ThinkingCard
Expandable card for thinking content.

```
┌──────────────────────────────────────────────────────────────┐
│ 💭 Thinking                                            [▼]   │
├──────────────────────────────────────────────────────────────┤
│ I need to check what files exist in the project...           │
└──────────────────────────────────────────────────────────────┘
```

- Auto-expands while streaming, auto-collapses when done
- User can manually toggle

### ToolCallPill
Expandable pill showing description + command, raw output when expanded.

```
┌──────────────────────────────────────────────────────────────┐
│ ✓ Listing output directory                             [▼]   │
│   ls outputs/                                                │
├──────────────────────────────────────────────────────────────┤
│ file1.txt                                                    │
│ file2.txt                                                    │
└──────────────────────────────────────────────────────────────┘
```

**Status icons**: ○ pending (gray) | ◐ in_progress (blue) | ✓ completed (green) | ✗ failed (red)

**Description/command extraction**:
| Kind | Description | Command |
|------|-------------|---------|
| execute | `rawInput.description` or "Running command" | `rawInput.command` |
| read | "Reading file" | `rawInput.filePath` |
| other (patch) | "Updating file" | `file.relativePath (+N -M)` |

**Raw output extraction**:
| Kind | Source |
|------|--------|
| execute | `rawOutput.metadata.output` |
| read | `rawOutput.output` |
| patch | `rawOutput.metadata.diff` |

---

## Packet Processing

Convert packets to display items, merging adjacent text/thinking:

```typescript
function packetsToDisplayItems(packets: RawPacket[], isStreaming: boolean): DisplayItem[] {
  const items: DisplayItem[] = [];
  const toolCalls = new Map<string, ToolCallState>();
  let currentText = "";
  let currentThinking = "";

  for (const packet of packets) {
    switch (packet.type) {
      case "agent_message_chunk":
        if (currentThinking) {
          items.push({ type: "thinking", content: currentThinking, isStreaming: false });
          currentThinking = "";
        }
        currentText += packet.content.text;
        break;

      case "agent_thought_chunk":
        if (currentText) {
          items.push({ type: "text", content: currentText });
          currentText = "";
        }
        currentThinking += packet.content.text;
        break;

      case "tool_call_start":
        // Flush accumulated content
        if (currentText) { items.push({ type: "text", content: currentText }); currentText = ""; }
        if (currentThinking) { items.push({ type: "thinking", content: currentThinking, isStreaming: false }); currentThinking = ""; }
        // Create tool call
        const tc = { id: packet.toolCallId, kind: packet.kind, title: packet.title, status: "pending", description: "", command: "", rawOutput: "" };
        toolCalls.set(packet.toolCallId, tc);
        items.push({ type: "tool_call", toolCall: tc });
        break;

      case "tool_call_progress":
        const existing = toolCalls.get(packet.toolCallId);
        if (existing) {
          existing.status = packet.status;
          existing.description = getDescription(packet);
          existing.command = getCommand(packet);
          existing.rawOutput = getRawOutput(packet);
        }
        break;
    }
  }

  // Flush remaining
  if (currentText) items.push({ type: "text", content: currentText });
  if (currentThinking) items.push({ type: "thinking", content: currentThinking, isStreaming });

  return items;
}
```

---

## Implementation Plan

### Phase 1: Types & Utils
- `types/packets.ts` - packet types
- `types/displayTypes.ts` - display item types
- `utils/packetProcessor.ts` - packetsToDisplayItems()

### Phase 2: Components
- `BuildAIResponse.tsx` - main renderer
- `TextChunk.tsx` - markdown wrapper
- `ThinkingCard.tsx` - expandable thinking
- `ToolCallPill.tsx` - expandable tool call
- `RawOutputBlock.tsx` - scrollable code block

### Phase 3: Integration
- Update `BuildMessageList.tsx` to use `BuildAIResponse`
- Delete: `AIBuildMessage.tsx`, `AIMessageWithTools.tsx`, `BuildAgentTimeline.tsx`, `BuildToolCallRenderer.tsx`

---

## File Structure

```
web/src/app/build/
├── types/
│   ├── packets.ts
│   └── displayTypes.ts
├── utils/
│   └── packetProcessor.ts
└── components/
    ├── BuildAIResponse.tsx
    ├── TextChunk.tsx
    ├── ThinkingCard.tsx
    ├── ToolCallPill.tsx
    └── RawOutputBlock.tsx
```

---

## Testing Checklist

- [ ] Text chunks render as markdown, adjacent chunks merge
- [ ] Thinking card auto-expands while streaming, auto-collapses when done
- [ ] Tool pills show description + command, expand to show raw output
- [ ] Status icons update correctly (pending → in_progress → completed/failed)
- [ ] All items render in chronological order
- [ ] Interleaved text/thinking/tools display correctly
