# Deep Research: Frontend Integration

This document covers the frontend implementation for deep research, including state management, UI rendering, and API integration.

## Toggle State Management

### `useDeepResearchToggle` Hook

**File**: `web/src/hooks/useDeepResearchToggle.ts` (lines 1-55)

**Props**:
```typescript
interface UseDeepResearchToggleProps {
    chatSessionId: string | null;
    assistantId: number | undefined;
}
```

**Returns**: `{ deepResearchEnabled: boolean, toggleDeepResearch: () => void }`

**Behavior**:
- Defaults to `false`
- Resets to `false` when switching between chat sessions (not on first session creation from `null`)
- Resets to `false` when assistant changes
- Uses `useRef` to track previous session ID for transition detection

### Input Bar Button

**File**: `web/src/sections/input/AppInputBar.tsx`

**Visibility logic** (lines 386-398):
```typescript
const showDeepResearch = useMemo(() => {
    const deepResearchGloballyEnabled =
        combinedSettings?.settings?.deep_research_enabled ?? true;
    return (
        deepResearchGloballyEnabled &&
        hasSearchToolsAvailable(selectedAssistant?.tools || [])
    );
}, [...]);
```

The button is shown only when:
1. Global setting `deep_research_enabled` is `true` (defaults to `true`)
2. The selected assistant has search tools available (internal or web)

**Button rendering** (lines 706-717):
- Icon: `SvgHourglass`
- Variant: `"select"`
- Selected state when `deepResearchEnabled` is `true`
- Foldable when not selected

## API Integration

### Send Message Request

**File**: `web/src/app/app/services/lib.tsx`

**Interface** (lines 112-129):
```typescript
interface SendMessageParams {
    deepResearch?: boolean;
    // ... other params
}
```

**Payload construction** (line 153):
```typescript
const payload = {
    deep_research: deepResearch ?? false,
    // ... other fields
};
```

**Endpoint**: `POST /api/chat/send-chat-message`

### Chat Controller

**File**: `web/src/hooks/useChatController.ts`

**Submit props** (lines 77-92):
```typescript
interface OnSubmitProps {
    message: string;
    deepResearch: boolean;
    // ... other props
}
```

## Renderers

### Deep Research Plan Renderer

**File**: `web/src/app/app/message/messageComponents/timeline/renderers/deepresearch/DeepResearchPlanRenderer.tsx` (lines 1-75)

**Type**: `MessageRenderer<DeepResearchPlanPacket, FullChatState>`

**Behavior**:
1. Aggregates `DEEP_RESEARCH_PLAN_DELTA` content via `useMemo` (line 27-40)
2. Determines status: "Generated plan" or "Generating plan" (line 42)
3. Renders via `ExpandableTextDisplay` component with `MinimalMarkdown`
4. Icon: `SvgCircle`
5. Title: "Research Plan"

### Research Agent Renderer

**File**: `web/src/app/app/message/messageComponents/timeline/renderers/deepresearch/ResearchAgentRenderer.tsx` (lines 1-385)

**Type**: `MessageRenderer<ResearchAgentPacket, FullChatState>`

This is the most complex renderer. It handles the full lifecycle of a research agent, including nested tool calls and intermediate reports.

**Render modes** (lines 43-52):
| Mode | Description | Usage |
|------|-------------|-------|
| `FULL` | Shows all nested tool groups, research task, and report | Expanded step in timeline |
| `COMPACT` | Shows only latest active item (tool or report) | Collapsed step |
| `HIGHLIGHT` | Shows only latest active item with header embedded | Parallel streaming preview |

**Data processing**:
1. **Extract start packet** (lines 68-73): Gets `RESEARCH_AGENT_START` to extract `research_task`
2. **Separate packets** (lines 76-112): Splits into `parentPackets` (no sub_turn_index) and `nestedToolGroups` (grouped by sub_turn_index)

**NestedToolGroup interface** (lines 32-38):
```typescript
interface NestedToolGroup {
    sub_turn_index: number;
    toolType: string;
    status: string;    // "Complete" | "Running"
    isComplete: boolean;
    packets: Packet[];
}
```

**Rendering logic**:
- **HIGHLIGHT mode** (lines 189-287): Shows streaming report or running tool or research task text
- **FULL/COMPACT mode** (lines 289-384):
  - Research task in `StepContainer`
  - Nested tools via `TimelineRendererComponent` + `TimelineStepComposer`
  - Intermediate report in `StepContainer` with `SvgBookOpen` icon and `ExpandableTextDisplay`

### Renderer Selection

**File**: `web/src/app/app/message/messageComponents/renderMessageComponent.tsx` (lines 89-123)

Deep research packets are checked early (before other tool types):

```typescript
if (groupedPackets.packets.some(isDeepResearchPlanPacket)) {
    return DeepResearchPlanRenderer;
}
if (groupedPackets.packets.some(isResearchAgentPacket)) {
    return ResearchAgentRenderer;
}
```

## Page Integration

### AppPage

**File**: `web/src/refresh-pages/AppPage.tsx`

- Import: `useDeepResearchToggle` (line 39)
- Initialize toggle (line 124): `const { deepResearchEnabled, toggleDeepResearch } = useDeepResearchToggle({...})`
- Pass to submit handler (line 193): `deepResearch: deepResearchEnabled`

### NRFPage

**File**: `web/src/app/app/nrf/NRFPage.tsx`

- Same pattern as AppPage
- Uses `useDeepResearchToggle` hook (line 21)
- Passes props to `ChatUI` and `AppInputBar`

## Global Settings

### Settings Interface

**File**: `web/src/app/admin/settings/interfaces.ts`

```typescript
interface Settings {
    deep_research_enabled?: boolean;  // line 27
    // ... other settings
}
```

### Default Value

**File**: `web/src/components/settings/lib.ts` (lines 116-118)

```typescript
if (settings.deep_research_enabled == null) {
    settings.deep_research_enabled = true;
}
```

## Data Flow Summary

```
User clicks Deep Research button
    -> useDeepResearchToggle sets deepResearchEnabled=true
User submits message
    -> onSubmit({ message, deepResearch: true, ... })
    -> useChatController -> sendMessage({ deep_research: true })
    -> POST /api/chat/send-chat-message { deep_research: true }
Backend streams packets via SSE
    -> Packet grouper sorts by placement
    -> renderMessageComponent detects packet types
    -> DeepResearchPlanRenderer / ResearchAgentRenderer
    -> Rendered in chat timeline
```
