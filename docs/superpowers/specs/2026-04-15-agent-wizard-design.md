# Agent Creation Wizard — Design Spec

## Overview

Replace the current agent creation page (`/app/agents/create`) with a split-pane wizard: a free-form chat on the left and the full agent configuration form on the right. As the user describes their agent in natural language, the AI extracts fields and populates the form in real-time. The user can also edit the form directly at any time.

## Goals

- Make agent creation faster and more intuitive via conversational AI
- Preserve full access to all existing form fields (no simplified subset)
- Reuse existing form components and validation — no parallel implementation
- Edit flow (`/app/agents/edit/[id]`) remains unchanged (form only, no chat)

## Architecture

### Page Structure

**New component: `AgentWizardPage`** (`/web/src/refresh-pages/AgentWizardPage.tsx`)

- Renders at `/app/agents/create` (replaces `AgentEditorPage` for creation)
- Layout: flexbox row, left panel ~40% width, right panel ~60% width, full viewport height
- Both panels sit inside a single Formik context so chat and form share state
- Uses existing Onyx layout components (`SettingsLayouts`, `GeneralLayouts`, etc.)

### Component Hierarchy

```
/app/agents/create/page.tsx
  → AgentWizardPage
    → Formik (shared context)
      → Left Panel: AgentBuilderChat
      → Right Panel:
        → SettingsLayouts.Header (with Cancel + Create buttons)
        → AgentFormBody (extracted from AgentEditorPage)
```

```
/app/agents/edit/[id]/page.tsx  (UNCHANGED)
  → AgentEditorPage
    → Formik
      → SettingsLayouts.Header
      → AgentFormBody
```

### New Files

| File | Purpose |
|---|---|
| `web/src/refresh-pages/AgentWizardPage.tsx` | Split-pane layout wrapping chat + form in shared Formik |
| `web/src/components/agents/AgentBuilderChat.tsx` | Chat panel — message list, input, streaming response handling |
| `web/src/components/agents/AgentFormBody.tsx` | Extracted form body (all form sections from current AgentEditorPage) |
| `web/src/app/api/agent-wizard-chat/route.ts` | Streaming API endpoint for conversational agent building |

### Modified Files

| File | Change |
|---|---|
| `web/src/refresh-pages/AgentEditorPage.tsx` | Import and render `AgentFormBody` instead of inline form. Remove `AgentDescriptionParser` import. |
| `web/src/app/app/agents/create/page.tsx` | Import `AgentWizardPage` instead of `AgentEditorPage` |

### Deleted Files

| File | Reason |
|---|---|
| `web/src/components/agents/AgentDescriptionParser.tsx` | Replaced by the chat panel |

## Chat Panel: `AgentBuilderChat`

### State

```typescript
interface ChatMessage {
  role: "assistant" | "user";
  content: string;
}

// Local state — no persistence needed
const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
const [input, setInput] = useState("");
const [isStreaming, setIsStreaming] = useState(false);
```

### Welcome Message

```
Tell me about the agent you want to create. What should it do? Who is it for?
```

### Send Flow

1. User types message, hits send (Enter or button click)
2. Append user message to `messages`
3. POST to `/api/agent-wizard-chat` with:
   - `messages`: full conversation history
   - `currentValues`: current Formik values (so AI knows what's filled)
4. Stream the response using `EventSource` or `fetch` with `ReadableStream`
5. As text streams in, display it in a new assistant message bubble
6. When the stream completes, parse the field-update JSON block from the response
7. Apply field updates via `setFieldValue()` from `useFormikContext()`

### UI

- Uses existing Onyx design tokens and components
- Message bubbles: simple div containers with appropriate background colors from the theme
- Input area at the bottom with a text input and send button
- Scrolls to bottom on new messages
- Shows a typing indicator while streaming

## API Endpoint: `/api/agent-wizard-chat`

### Request

```typescript
POST /api/agent-wizard-chat
Content-Type: application/json

{
  messages: ChatMessage[],
  currentValues: {
    name: string,
    description: string,
    instructions: string,
    starter_messages: string[],
    web_search: boolean,
    image_generation: boolean,
    code_interpreter: boolean
  }
}
```

### Response

Server-Sent Events stream. Each event contains a chunk of the assistant's response text.

The final chunk includes a JSON field-update block delimited by markers:

```
Great, I've set up your quality control assistant! I added instructions for defect identification and root cause analysis using the 5 Whys method. I also suggested some conversation starters your team might use.

Want to attach any knowledge sources like your ISO documentation?

<<<FIELDS>>>
{
  "name": "Quality Control Assistant",
  "description": "Helps manufacturing workers identify defects, reference ISO standards, and perform root cause analysis.",
  "instructions": "You are a manufacturing quality control assistant...",
  "starter_messages": [
    "I found a surface defect on a stamped part — help me classify it",
    "Walk me through a root cause analysis for this recurring weld issue",
    "What does ISO 9001 say about corrective actions?"
  ],
  "web_search": false,
  "image_generation": false,
  "code_interpreter": false
}
<<<END>>>
```

### System Prompt

The system prompt instructs the LLM to:

1. Respond conversationally — confirm what was set up, suggest next steps
2. Extract agent configuration from the conversation context
3. Always include a `<<<FIELDS>>>...<<<END>>>` block with the current best-guess for all extractable fields
4. Only include fields that should change from the current values
5. Be aware of what's already filled (received via `currentValues`) and avoid re-suggesting the same values
6. Naturally guide the user toward filling important fields (instructions, starters) without being rigid

### Implementation

- Same LLM provider lookup pattern as existing `/api/agent-parse/route.ts`
- Same auth forwarding (cookie passthrough to backend `/admin/llm/provider`)
- Uses streaming APIs from OpenAI/Anthropic SDKs
- Falls back to non-streaming if the provider doesn't support it

## Field Update & Highlight

### Update Mechanism

The chat component parses the `<<<FIELDS>>>` block after streaming completes:

```typescript
const fieldsMatch = fullResponse.match(/<<<FIELDS>>>([\s\S]*?)<<<END>>>/);
if (fieldsMatch) {
  const updates = JSON.parse(fieldsMatch[1]);
  const displayText = fullResponse.replace(/<<<FIELDS>>>[\s\S]*?<<<END>>>/, "").trim();

  // Apply each changed field
  Object.entries(updates).forEach(([key, value]) => {
    setFieldValue(key, value);
    setFieldTouched(key, true, false);
    markFieldUpdated(key); // for highlight animation
  });
}
```

The `<<<FIELDS>>>` block is stripped from the displayed message — the user only sees the conversational text.

### Highlight Animation

Track recently-updated fields in a `Set<string>` state. When a field is updated by the chat, add it to the set. Clear it after 2 seconds via `setTimeout`.

The form body component receives the set as a prop and applies a CSS class (e.g., `ring-2 ring-accent transition-all duration-500`) to fields whose names are in the set.

This is a light touch — just a brief border highlight that fades, using existing Tailwind utilities.

## Form Extraction: `AgentFormBody`

Extract the form body from `AgentEditorPage` (lines ~1258-1610, everything inside `<SettingsLayouts.Body>`) into a standalone component.

### Props

```typescript
interface AgentFormBodyProps {
  existingAgent?: FullPersona | null;
  highlightedFields?: Set<string>;  // fields recently updated by chat
}
```

### What Moves

All form sections move to `AgentFormBody`:
- General (name, description, avatar)
- Instructions & Conversation Starters
- Knowledge pane
- Actions (tools, MCP servers, OpenAPI)
- Advanced Options (sharing, model, reminders)

### What Stays in AgentEditorPage

- The Formik wrapper (initialValues, validation, handleSubmit)
- Hook calls for data (useDocumentSets, useMcpServersForAgentEditor, etc.)
- Modals (share, delete, user files)
- The SettingsLayouts.Root and Header

The data from hooks gets passed down as props to `AgentFormBody`. This keeps the form body a presentational component.

### AgentEditorPage After Extraction

```typescript
// Simplified — just wraps Formik + header + form body
export default function AgentEditorPage({ agent, refreshAgent }) {
  // ... all existing hooks and handlers stay here ...

  return (
    <Formik ...>
      {({ ... }) => (
        <Form>
          <SettingsLayouts.Root>
            <SettingsLayouts.Header ... />
            <SettingsLayouts.Body>
              <AgentFormBody existingAgent={agent} />
            </SettingsLayouts.Body>
          </SettingsLayouts.Root>
        </Form>
      )}
    </Formik>
  );
}
```

## Routing

### `/app/agents/create/page.tsx`

```typescript
// Before: import AgentEditorPage
// After:
import AgentWizardPage from "@/refresh-pages/AgentWizardPage";

export default function CreateAgentPage() {
  return <AgentWizardPage />;
}
```

### `/app/agents/edit/[id]/page.tsx`

No changes. Continues to use `AgentEditorPage`.

## Edge Cases

- **Empty chat submit**: Disabled send button when input is empty
- **Rapid messages**: Disable input while streaming; queue not needed since user waits for response
- **LLM parse failure**: If `<<<FIELDS>>>` block is malformed, silently skip field updates — the conversational response still displays. Log the error.
- **Manual form edits during chat**: Work fine — Formik state is the source of truth. Next chat message sends `currentValues` which includes manual edits, so the AI stays in sync.
- **No LLM providers configured**: Show an error message in the chat panel and fall back to form-only mode (user can still fill the form manually).
