# AIMessage and MultiToolRenderer Requirements Document

> **Purpose:** This document captures everything the AIMessage.tsx and MultiToolRenderer.tsx components do, including all edge cases, to aid in refactoring.

## Table of Contents
1. [Overview](#1-overview)
2. [AIMessage Component](#2-aimessage-component)
3. [MultiToolRenderer Component](#3-multitoolrenderer-component)
4. [Packet Types and Streaming Models](#4-packet-types-and-streaming-models)
5. [Interfaces](#5-interfaces)
6. [Hooks](#6-hooks)
7. [Utility Functions](#7-utility-functions)
8. [Renderers](#8-renderers)
9. [Edge Cases](#9-edge-cases)
10. [Data Flow](#10-data-flow)
11. [State Management](#11-state-management)
12. [Timing Logic](#12-timing-logic)
13. [Citations and Documents](#13-citations-and-documents)

---

## 1. Overview

### Purpose
These components render AI responses in the Onyx chat interface, handling:
- Streaming message content with real-time updates
- Tool execution display (search, code, image generation, etc.)
- Parallel tool support
- Citations and document references
- Feedback collection (like/dislike)
- Message regeneration and switching

### Architecture Pattern
```
rawPackets (backend stream)
    |
AIMessage (incremental processing)
    |
Groups packets by (turn_index, tab_index)
    |
Split into:
+-- toolGroups --> MultiToolRenderer
|   +-- Timeline of tool executions
+-- displayGroups --> RendererComponent
    +-- Main message content
```

---

## 2. AIMessage Component

### Location
`/web/src/app/chat/message/messageComponents/AIMessage.tsx`

### Props (AIMessageProps)

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `rawPackets` | `Packet[]` | Yes | Streaming packets from backend |
| `chatState` | `FullChatState` | Yes | Assistant, docs, citations, model info |
| `nodeId` | `number` | Yes | Unique ID in message tree |
| `messageId` | `number` | No | ID for feedback/regeneration |
| `currentFeedback` | `FeedbackType \| null` | No | Current like/dislike state |
| `llmManager` | `LlmManager \| null` | Yes | LLM selection manager |
| `otherMessagesCanSwitchTo` | `number[]` | No | Alternative message node IDs |
| `onMessageSelection` | `(nodeId: number) => void` | No | Message switch callback |
| `onRegenerate` | `RegenerationFactory` | No | Regeneration factory function |
| `parentMessage` | `Message \| null` | No | Parent for regeneration context |

### RegenerationFactory Type
```typescript
type RegenerationFactory = (regenerationRequest: {
  messageId: number;
  parentMessage: Message;
  forceSearch?: boolean;
}) => (modelOverride: LlmDescriptor) => Promise<void>;
```

### Memoization
Uses `React.memo` with custom `arePropsEqual` function comparing:
- `nodeId`, `messageId`, `currentFeedback`
- `rawPackets.length` (assumes append-only)
- `chatState.assistant?.id`, `chatState.docs`, `chatState.citations`
- `chatState.overriddenModel`, `chatState.researchType`
- `otherMessagesCanSwitchTo`, `onRegenerate`
- `parentMessage?.messageId`, `llmManager?.isLoadingProviders`

### Internal State

| State/Ref | Type | Purpose |
|-----------|------|---------|
| `lastProcessedIndexRef` | `number` | Tracks processed packet index |
| `citationsRef` | `StreamingCitation[]` | Accumulates citations |
| `seenCitationDocIdsRef` | `Set<string>` | Citation deduplication |
| `citationMapRef` | `CitationMap` | citation_num -> document_id |
| `documentMapRef` | `Map<string, OnyxDocument>` | Document storage by ID |
| `groupedPacketsMapRef` | `Map<string, Packet[]>` | Groups by "turn-tab" key |
| `groupedPacketsRef` | `Array<{turn_index, tab_index, packets}>` | Sorted groups |
| `finalAnswerComingRef` | `boolean` | Message content incoming |
| `displayCompleteRef` | `boolean` | All content rendered |
| `stopPacketSeenRef` | `boolean` | STOP packet received |
| `stopReasonRef` | `StopReason` | Why stream stopped |
| `seenGroupKeysRef` | `Set<string>` | Tracked group keys |
| `groupKeysWithSectionEndRef` | `Set<string>` | Groups with SECTION_END |
| `expectedBranchesRef` | `Map<number, number>` | Expected parallel branches per turn |

### Key Behaviors

#### 1. Incremental Packet Processing
- Processes only NEW packets (from `lastProcessedIndexRef.current`)
- Resets all state when `nodeId` changes
- Resets if `rawPackets.length < lastProcessedIndexRef.current`

#### 2. Packet Grouping
- Groups by composite key: `"${turn_index}-${tab_index}"`
- Same turn_index + different tab_index = parallel tools
- TOP_LEVEL_BRANCHING packets set expected branch count (not grouped)

#### 3. Synthetic SECTION_END Injection
- Injects SECTION_END when moving to a new turn_index
- Injects for all groups when STOP packet arrives
- Ensures graceful tool completion

#### 4. Content Splitting
```typescript
// Tools go to MultiToolRenderer
const toolGroups = groupedPackets.filter(g => isToolPacket(g.packets[0], false));

// Display content (messages, images, python) go to main area
const displayGroups = (finalAnswerComing || toolGroups.length === 0)
  ? groupedPackets.filter(g => isDisplayPacket(g.packets[0]))
  : [];
```

#### 5. Citation Processing
- Extracts CITATION_INFO packets immediately
- Adds to `citationMapRef` for real-time rendering
- Deduplicates using `seenCitationDocIdsRef`

#### 6. Document Extraction
- From SEARCH_TOOL_DOCUMENTS_DELTA packets
- From FETCH_TOOL_DOCUMENTS packets
- Stored in `documentMapRef`

#### 7. Feedback Handling
- Toggle logic: clicking same button removes feedback
- Like: Opens modal if NEXT_PUBLIC_POSITIVE_PREDEFINED_FEEDBACK_OPTIONS set
- Dislike: Always opens FeedbackModal

#### 8. UI Elements Rendered
- AgentAvatar for assistant
- MultiToolRenderer for tools (if any)
- RendererComponent for display content
- Feedback buttons (when complete)
- Copy button
- Message switcher (when alternatives exist)
- Regenerate/LLM popover
- CitedSourcesToggle

---

## 3. MultiToolRenderer Component

### Location
`/web/src/app/chat/message/messageComponents/MultiToolRenderer.tsx`

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `packetGroups` | `Array<{turn_index, tab_index, packets}>` | Yes | Tool packet groups |
| `chatState` | `FullChatState` | Yes | Chat state for renderers |
| `isComplete` | `boolean` | Yes | All tools finished |
| `isFinalAnswerComing` | `boolean` | Yes | Final answer expected |
| `stopPacketSeen` | `boolean` | Yes | STOP packet received |
| `stopReason` | `StopReason` | No | Why stopped (finished/cancelled) |
| `onAllToolsDisplayed` | `() => void` | No | Callback when all visible |
| `isStreaming` | `boolean` | No | Global streaming state |
| `expectedBranchesPerTurn` | `Map<number, number>` | No | Expected parallel branches |

### Internal Types

```typescript
enum DisplayType {
  REGULAR = "regular",           // Standard tool
  SEARCH_STEP_1 = "search-step-1", // Internal search: querying
  SEARCH_STEP_2 = "search-step-2", // Internal search: reading docs
}

type DisplayItem = {
  key: string;           // "turn-tab" or "turn-tab-search-1/2"
  type: DisplayType;
  turn_index: number;
  tab_index: number;
  packets: Packet[];
};
```

### Internal State

| State | Type | Purpose |
|-------|------|---------|
| `isExpanded` | `boolean` | Summary expanded (complete state) |
| `isStreamingExpanded` | `boolean` | Expanded during streaming |

### Key Behaviors

#### 1. Display Item Transformation
- Internal search tools split into SEARCH_STEP_1 + SEARCH_STEP_2
- SEARCH_STEP_2 only added if `hasResults || isComplete`
- Other tools remain as single REGULAR items

#### 2. Tool Visibility Control (via useToolDisplayTiming)
- Shows tools sequentially by turn_index
- Parallel tools (same turn, different tab) shown together
- Enforces minimum 1500ms display per tool

#### 3. Shimmer Control
```typescript
const shouldStopShimmering = stopPacketSeen || isStreaming === false || isComplete;
```

#### 4. Two Render Modes

**Streaming Mode (isComplete = false):**
- Shows progressively visible tools
- Uses ToolItemRow for compact display
- Parallel tools rendered via ParallelToolTabs
- Border with rounded corners, padding, shadow

**Complete Mode (isComplete = true):**
- Shows "{n} steps" summary header
- Click to expand/collapse
- Shows all tools with ExpandedToolItem
- "Done" node at bottom (or "Completed with errors")

#### 5. ParallelToolTabs Sub-component
- Tabbed interface for parallel tools
- Tab bar shows name, icon, status indicator
- Navigation arrows (< >) for tab switching
- Keyboard navigation (ArrowLeft/Right)
- Collapse/expand toggle
- Status icons: spinner (loading), checkmark (done), X (error/cancelled)

### Rendered Elements
- Timeline connector lines between tools
- Tool icons and status text
- Expandable content areas
- Branch icon (FiGitBranch) for parallel tools
- Completion indicators

---

## 4. Packet Types and Streaming Models

### Location
`/web/src/app/chat/services/streamingModels.ts`

### Placement Structure
```typescript
interface Placement {
  turn_index: number;           // Sequential execution order
  tab_index?: number;           // Parallel tool identifier
  sub_turn_index?: number | null; // Nested tool within research agent
}
```

### PacketType Enum (Complete List)

**Message Packets:**
- `MESSAGE_START` - Initial message with final_documents
- `MESSAGE_DELTA` - Streamed content chunk
- `MESSAGE_END` - Message complete

**Control Packets:**
- `STOP` - Stream ended (with stop_reason)
- `SECTION_END` - Tool/section complete
- `TOP_LEVEL_BRANCHING` - Announces parallel branches
- `ERROR` - Tool error with message

**Search Tool:**
- `SEARCH_TOOL_START` - Start with is_internet_search flag
- `SEARCH_TOOL_QUERIES_DELTA` - Search queries
- `SEARCH_TOOL_DOCUMENTS_DELTA` - Found documents

**Python Tool:**
- `PYTHON_TOOL_START` - Code to execute
- `PYTHON_TOOL_DELTA` - stdout, stderr, file_ids

**Image Generation:**
- `IMAGE_GENERATION_TOOL_START` - Generation started
- `IMAGE_GENERATION_TOOL_DELTA` - Generated images

**Fetch/URL Tool:**
- `FETCH_TOOL_START` - URL fetching started
- `FETCH_TOOL_URLS` - URLs being fetched
- `FETCH_TOOL_DOCUMENTS` - Extracted documents

**Custom Tool:**
- `CUSTOM_TOOL_START` - Custom tool name
- `CUSTOM_TOOL_DELTA` - Tool response data

**Reasoning:**
- `REASONING_START` - Thinking started
- `REASONING_DELTA` - Thinking content
- `REASONING_DONE` - Thinking complete

**Citations:**
- `CITATION_INFO` - citation_number -> document_id

**Deep Research:**
- `DEEP_RESEARCH_PLAN_START/DELTA` - Plan generation
- `RESEARCH_AGENT_START` - Agent task
- `INTERMEDIATE_REPORT_START/DELTA` - Agent report
- `INTERMEDIATE_REPORT_CITED_DOCS` - Report citations

### StopReason Enum
```typescript
enum StopReason {
  FINISHED = "finished",
  USER_CANCELLED = "user_cancelled"
}
```

---

## 5. Interfaces

### Location
`/web/src/app/chat/message/messageComponents/interfaces.ts`

### FullChatState
```typescript
interface FullChatState {
  assistant: MinimalPersonaSnapshot;
  docs?: OnyxDocument[] | null;
  userFiles?: ProjectFile[];
  citations?: CitationMap;
  setPresentingDocument?: (document: MinimalOnyxDocument) => void;
  regenerate?: (modelOverride: LlmDescriptor) => Promise<void>;
  overriddenModel?: string;
  researchType?: string | null;
}
```

### RendererResult
```typescript
interface RendererResult {
  icon: IconType | OnyxIconType | null;
  status: string | JSX.Element | null;
  content: JSX.Element;
  expandedText?: JSX.Element;  // Override for expanded view
}
```

### MessageRenderer Type
```typescript
type MessageRenderer<T extends Packet, S extends Partial<FullChatState>> =
  React.ComponentType<{
    packets: T[];
    state: S;
    onComplete: () => void;
    renderType: RenderType;
    animate: boolean;
    stopPacketSeen: boolean;
    children: (result: RendererResult) => JSX.Element;
  }>;
```

### RenderType Enum
```typescript
enum RenderType {
  HIGHLIGHT = "highlight",  // Short/collapsed
  FULL = "full",            // Detailed view
}
```

### CitationMap
```typescript
type CitationMap = { [citation_num: number]: string };
```

### StreamingCitation
```typescript
interface StreamingCitation {
  citation_num: number;
  document_id: string;
}
```

---

## 6. Hooks

### useMessageSwitching
**Location:** `hooks/useMessageSwitching.ts`

```typescript
interface UseMessageSwitchingProps {
  nodeId: number;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (messageId: number) => void;
}

interface UseMessageSwitchingReturn {
  currentMessageInd: number | undefined;
  includeMessageSwitcher: boolean;
  getPreviousMessage: () => number | undefined;
  getNextMessage: () => number | undefined;
}
```

**Behavior:**
- Finds current message index in alternatives
- Shows switcher if alternatives > 1
- Handles circular navigation

### useToolDisplayTiming
**Location:** `hooks/useToolDisplayTiming.ts`

```typescript
function useToolDisplayTiming(
  toolGroups: Array<{turn_index, tab_index, packets}>,
  isFinalAnswerComing: boolean,
  isComplete: boolean,
  expectedBranchesPerTurn?: Map<number, number>
): {
  visibleTools: Set<string>;  // "turn-tab" keys
  handleToolComplete: (turnIndex, tabIndex?) => void;
  allToolsDisplayed: boolean;
}
```

**Constants:**
- `MINIMUM_DISPLAY_TIME_MS = 1500`

**Behavior:**
- Shows tools sequentially by turn_index
- Parallel tools (same turn) shown together
- Waits for expected branches before advancing
- Enforces minimum display duration
- Tracks completion state

### usePacketAnimationAndCollapse
**Location:** `hooks/usePacketAnimationAndCollapse.ts`

```typescript
function usePacketAnimationAndCollapse({
  packets: Packet[];
  animate: boolean;
  isComplete: boolean;
  onComplete: () => void;
  preventDoubleComplete?: boolean;
}): {
  displayedPacketCount: number;  // -1 = all
  isExpanded: boolean;
  toggleExpanded: () => void;
}
```

**Constants:**
- `PACKET_DELAY_MS = 10`

**Behavior:**
- Gradually reveals packets during animation
- Auto-collapses on completion
- Prevents double onComplete calls

### useFeedbackController
**Location:** `/web/src/app/chat/hooks/useFeedbackController.ts`

```typescript
interface UseFeedbackControllerProps {
  setPopup: (popup: PopupSpec | null) => void;
}

function useFeedbackController(props): {
  handleFeedbackChange: (
    messageId: number,
    newFeedback: FeedbackType | null,
    feedbackText?: string,
    predefinedFeedback?: string
  ) => Promise<boolean>
}
```

**Behavior:**
- Optimistic UI updates
- Calls backend API
- Rollback on error
- Shows popup on failure

### Store Hooks (useChatSessionStore)
**Location:** `/web/src/app/chat/stores/useChatSessionStore.ts`

Used hooks:
- `useCurrentChatState()` -> "streaming" | "input" | ...
- `useDocumentSidebarVisible()` -> boolean
- `useSelectedNodeForDocDisplay()` -> number | null
- `updateCurrentDocumentSidebarVisible(visible)`
- `updateCurrentSelectedNodeForDocDisplay(nodeId)`

---

## 7. Utility Functions

### packetUtils.ts
**Location:** `/web/src/app/chat/services/packetUtils.ts`

| Function | Description |
|----------|-------------|
| `isToolPacket(packet, includeSectionEnd?)` | Checks if packet is any tool type |
| `isActualToolCallPacket(packet)` | Tool packet excluding reasoning |
| `isDisplayPacket(packet)` | MESSAGE_START, IMAGE_GENERATION, PYTHON |
| `isFinalAnswerComing(packets)` | Checks for display packet types |
| `isStreamingComplete(packets)` | Checks for STOP packet |
| `getTextContent(packets)` | Extracts all message text |
| `groupPacketsByTurnIndex(packets)` | Groups by turn/tab |

### toolDisplayHelpers.tsx
**Location:** `messageComponents/toolDisplayHelpers.tsx`

| Function | Description |
|----------|-------------|
| `parseToolKey(key)` | Parses "turn-tab" to {turn_index, tab_index} |
| `getToolKey(turn_index, tab_index)` | Creates "turn-tab" key |
| `getToolName(packets)` | Human-readable tool name |
| `getToolIcon(packets)` | Tool icon component |
| `isToolComplete(packets)` | Checks SECTION_END/ERROR |
| `hasToolError(packets)` | Checks for ERROR packet |

**getToolName Mapping:**
- SEARCH_TOOL_START -> "Web Search" or "Internal Search"
- PYTHON_TOOL_START -> "Code Interpreter"
- FETCH_TOOL_START -> "Open URLs"
- CUSTOM_TOOL_START -> Custom name
- IMAGE_GENERATION_TOOL_START -> "Generate Image"
- DEEP_RESEARCH_PLAN_START -> "Generate plan"
- RESEARCH_AGENT_START -> "Research agent"
- REASONING_START -> "Thinking"

**isToolComplete Special Case:**
- For RESEARCH_AGENT_START: Only parent-level SECTION_END (sub_turn_index === undefined)
- Prevents marking complete when nested tool finishes

### thinkingTokens.ts
**Location:** `/web/src/app/chat/services/thinkingTokens.ts`

| Function | Description |
|----------|-------------|
| `removeThinkingTokens(content)` | Removes `<think>...</think>` tags |
| `hasCompletedThinkingTokens(content)` | Check for complete blocks |
| `hasPartialThinkingTokens(content)` | Check for streaming blocks |
| `extractThinkingContent(content)` | Get thinking text |
| `isThinkingComplete(content)` | Check if tags balanced |

### copyingUtils.tsx
**Location:** `messageComponents/copyingUtils.tsx`

| Function | Description |
|----------|-------------|
| `handleCopy(event, markdownRef)` | Custom copy with HTML preservation |
| `convertMarkdownTablesToTsv(content)` | Tables to TSV for spreadsheets |
| `copyAll(content)` | Copy with HTML + plain text |

---

## 8. Renderers

### Location
`/web/src/app/chat/message/messageComponents/renderers/`

### RendererComponent (Router)
**Location:** `renderMessageComponent.tsx`

**findRenderer() Selection Order:**
1. MessageTextRenderer - MESSAGE_START/DELTA/END
2. DeepResearchPlanRenderer - Deep research plan
3. ResearchAgentRenderer - Research agent
4. SearchToolRenderer - Search tool
5. ImageToolRenderer - Image generation
6. PythonToolRenderer - Python execution
7. CustomToolRenderer - Custom tools
8. FetchToolRenderer - URL fetching
9. ReasoningRenderer - Thinking/reasoning

### MessageTextRenderer
- Animated packet-by-packet display (10ms delay)
- BlinkingDot during streaming
- Markdown rendering with citations
- Waits for animation before onComplete

### SearchToolRenderer
- Differentiates web vs internal search
- Two-step display: querying -> reading
- Minimum display duration (1000ms each)
- Expandable query/document lists
- Constants: INITIAL_QUERIES_TO_SHOW=3, QUERIES_PER_EXPANSION=5
- Constants: INITIAL_RESULTS_TO_SHOW=3, RESULTS_PER_EXPANSION=10

### FetchToolRenderer
- Three stages: start -> URLs -> documents
- Minimum display duration (1000ms)
- Falls back to URLs if no documents

### ReasoningRenderer
- Minimum display time (500ms)
- Provides expandedText override
- No icon in header

### ImageToolRenderer
- HIGHLIGHT vs FULL render modes
- Loading animation during generation
- 1-2 column grid for images

### PythonToolRenderer
- Syntax highlighting (highlight.js)
- Shows code, stdout, stderr, files
- Error highlighting for failures

### CustomToolRenderer
- JSON/text data responses
- File downloads support
- Image, CSV, generic responses

### DeepResearchPlanRenderer
- Auto-collapse on completion
- Markdown plan content
- Collapsible chevron

### ResearchAgentRenderer
- Separates parent from nested tools
- Recursive RendererComponent for nested
- Shows task, tools, report
- Step count in collapsed view

---

## 9. Edge Cases

### User Cancellation
```typescript
const isCancelled = stopReason === StopReason.USER_CANCELLED;
```
- Shows X icon instead of checkmark
- Stops shimmer immediately
- Skips minimum display timing for search tools
- Passed to all ToolItemRow components

### Tool Errors
- ERROR packet treated as completion
- Shows red X icon in tabs
- "Completed with errors" in Done node
- Tool still displays content

### Loading States
```typescript
const isLoading = !isItemComplete && !shouldStopShimmering;
```
- Shimmer classes: `text-shimmer-base`, `loading-text`
- LoadingSpinner in inactive tabs
- BlinkingDot in empty slots

### Research Agents with Nested Tools
- Nested tools have sub_turn_index set
- Only parent SECTION_END marks agent complete
- Prevents premature completion detection

### Parallel Tools with Expected Branches
- TOP_LEVEL_BRANCHING declares count
- useToolDisplayTiming waits for all branches
- Tools grouped visually with branch icon

### Internal vs Internet Search
- Internal: Split into two display steps
- Internet: Single REGULAR display
- Determined by is_internet_search flag

### Search with No Results
- Shows queries but no documents
- BlinkingDot where results would be
- X icon if cancelled

### Stream Reset
```typescript
if (lastProcessedIndexRef.current > rawPackets.length) {
  resetState();
}
```
- Handles when packets replaced with shorter array
- Full state reset occurs

### Final Answer Reset
```typescript
if (finalAnswerComingRef.current && !stopPacketSeenRef.current &&
    isActualToolCallPacket(packet)) {
  setFinalAnswerComing(false);
  setDisplayComplete(false);
}
```
- When message followed by tool call (not reasoning)
- Hides message content until tools complete

### Empty Packet Groups
- Filtered out if no content packets
- Content packets: MESSAGE_START, tool starts, etc.

### Feedback Toggle
- Clicking same button removes feedback
- Like may open modal if predefined options exist
- Dislike always opens modal

### Document Sidebar Toggle
- Same message click closes sidebar
- Different message click switches content

---

## 10. Data Flow

### Complete Flow Diagram
```
Backend SSE Stream
    |
rawPackets[] array
    |
AIMessage Component
    |
    +-- Incremental Processing Loop
    |   +-- Skip TOP_LEVEL_BRANCHING (store in expectedBranchesRef)
    |   +-- Group by "turn_index-tab_index"
    |   +-- Extract CITATION_INFO -> citationMapRef
    |   +-- Extract documents -> documentMapRef
    |   +-- Track finalAnswerComing state
    |   +-- Inject SECTION_END at turn boundaries
    |   +-- Handle STOP packet (inject all SECTION_ENDs)
    |
    +-- groupedPacketsRef (sorted by turn, tab)
    |
    +-- effectiveChatState (merge streaming citations)
    |
    +-- Split packets:
    |   +-- toolGroups (isToolPacket) ----------------+
    |   +-- displayGroups (isDisplayPacket) ------+   |
    |                                             |   |
    |   +------------------------------------------+  |
    |   |                                             |
    |   v                                             |
    |   RendererComponent                             |
    |   +-- findRenderer() -> MessageTextRenderer     |
    |   |                  -> ImageToolRenderer       |
    |   |                  -> PythonToolRenderer      |
    |   +-- Children callback                         |
    |                                                 |
    |   +----------------------------------------------+
    |   |
    |   v
    |   MultiToolRenderer
    |   +-- Transform to DisplayItems
    |   |   +-- Internal search -> STEP_1 + STEP_2
    |   |   +-- Other tools -> REGULAR
    |   |
    |   +-- useToolDisplayTiming()
    |   |   +-- visibleTools Set
    |   |   +-- handleToolComplete callback
    |   |   +-- allToolsDisplayed flag
    |   |
    |   +-- Streaming View (isComplete=false)
    |   |   +-- visibleTurnGroups
    |   |       +-- Parallel -> ParallelToolTabs
    |   |       +-- Single -> ToolItemRow + Renderer
    |   |
    |   +-- Complete View (isComplete=true)
    |       +-- "{n} steps" summary
    |       +-- Expanded: ExpandedToolItem + Done
    |
    +-- UI Controls
        +-- FeedbackModal (like/dislike)
        +-- MessageSwitcher (alternatives)
        +-- CopyIconButton
        +-- LLMPopover (regeneration)
        +-- CitedSourcesToggle
```

### Packet Processing Order
1. TOP_LEVEL_BRANCHING -> expectedBranchesRef
2. Group packet by key
3. CITATION_INFO -> citationMapRef + citationsRef
4. SEARCH_TOOL_DOCUMENTS_DELTA -> documentMapRef
5. FETCH_TOOL_DOCUMENTS -> documentMapRef
6. Display packet types -> set finalAnswerComing
7. STOP -> set stopPacketSeen, inject SECTION_ENDs

---

## 11. State Management

### AIMessage State Lifecycle

**On Mount / nodeId Change:**
```typescript
resetState() -> Clear all refs to initial values
```

**Per Render (new packets):**
```typescript
for (i = lastProcessedIndex; i < rawPackets.length; i++) {
  // Process packet
}
lastProcessedIndexRef.current = rawPackets.length;
```

**State Transitions:**
```
Initial -> (MESSAGE_START) -> finalAnswerComing=true
finalAnswerComing -> (tool packet) -> finalAnswerComing=false
finalAnswerComing -> (STOP) -> stopPacketSeen=true
stopPacketSeen -> (render complete) -> displayComplete=true
```

### MultiToolRenderer State Lifecycle

**Tool Visibility:**
```
useToolDisplayTiming manages visibleTools Set
+-- Start: First turn's tools visible
+-- handleToolComplete called
+-- Check elapsed time >= 1500ms
|   +-- Yes: Mark complete, show next turn
|   +-- No: Schedule timeout for remaining time
+-- allToolsDisplayed when all turns visible + complete
```

**Expansion State:**
```
Streaming: isStreamingExpanded
    | (isComplete becomes true)
Complete: isExpanded = isStreamingExpanded (preserved)
```

---

## 12. Timing Logic

### Tool Display Timing Constants
```typescript
MINIMUM_DISPLAY_TIME_MS = 1500  // Per tool minimum
```

### Search Renderer Timing
```typescript
SEARCHING_MIN_DURATION_MS = 1000  // "Searching" phase
SEARCHED_MIN_DURATION_MS = 1000   // "Reading" phase
```

### Fetch Renderer Timing
```typescript
READING_MIN_DURATION_MS = 1000
```

### Reasoning Renderer Timing
```typescript
THINKING_MIN_DURATION_MS = 500
```

### Animation Timing
```typescript
PACKET_DELAY_MS = 10  // Between packet reveals
```

### Timing Flow
```
Tool Group Visible
    |
Record start time (toolStartTimesRef)
    |
Tool completes (handleToolComplete called)
    |
Calculate elapsed = now - startTime
    |
elapsed >= 1500ms?
+-- Yes: Mark complete immediately
+-- No: setTimeout(markComplete, 1500 - elapsed)
    |
All parallel tools complete?
+-- Yes: Show next turn's tools
+-- No: Wait for remaining tools
```

---

## 13. Citations and Documents

### Citation Processing

**During Streaming:**
```typescript
if (packet.obj.type === PacketType.CITATION_INFO) {
  citationMapRef.current[citation_number] = document_id;
  if (!seenCitationDocIdsRef.current.has(document_id)) {
    seenCitationDocIdsRef.current.add(document_id);
    citationsRef.current.push({ citation_num, document_id });
  }
}
```

**Effective Citations:**
```typescript
const effectiveChatState = {
  ...chatState,
  citations: {
    ...chatState.citations,      // Props citations
    ...streamingCitationMap,     // Streaming (takes precedence)
  },
};
```

### Document Sources

1. **SEARCH_TOOL_DOCUMENTS_DELTA:**
   ```typescript
   docDelta.documents.forEach(doc => {
     documentMapRef.current.set(doc.document_id, doc);
   });
   ```

2. **FETCH_TOOL_DOCUMENTS:**
   ```typescript
   fetchDocuments.documents.forEach(doc => {
     documentMapRef.current.set(doc.document_id, doc);
   });
   ```

3. **MESSAGE_START.final_documents:**
   - Available in chatState.docs
   - Not extracted in packet loop

### CitedSourcesToggle Display
```typescript
{nodeId && (citations.length > 0 || documentMap.size > 0) && (
  <CitedSourcesToggle
    citations={citations}
    documentMap={documentMap}
    nodeId={nodeId}
    onToggle={...}
  />
)}
```

### Document Sidebar Control
```typescript
onToggle={(toggledNodeId) => {
  if (selectedMessageForDocDisplay === toggledNodeId && documentSidebarVisible) {
    // Close sidebar
    updateCurrentDocumentSidebarVisible(false);
    updateCurrentSelectedNodeForDocDisplay(null);
  } else {
    // Open/switch sidebar
    updateCurrentSelectedNodeForDocDisplay(toggledNodeId);
    updateCurrentDocumentSidebarVisible(true);
  }
}}
```

---

## Verification Checklist

After refactoring, verify:

- [ ] Streaming messages render incrementally
- [ ] Tools display in correct order with timing
- [ ] Parallel tools show together with tabs
- [ ] Internal search shows two-step process
- [ ] Citations appear as clickable links
- [ ] Document sidebar toggles correctly
- [ ] Feedback buttons work (like/dislike/toggle)
- [ ] Copy preserves markdown formatting
- [ ] Message switching works between alternatives
- [ ] Regeneration with model override works
- [ ] User cancellation shows X icon, stops shimmer
- [ ] Tool errors show red X, "Completed with errors"
- [ ] Research agents show nested tools correctly
- [ ] Deep research plans auto-collapse
- [ ] All minimum display times respected
- [ ] State resets on nodeId change
- [ ] No duplicate onComplete calls
