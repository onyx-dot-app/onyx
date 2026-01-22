# Build/V1 Chat UI Frontend Rendering Overview

## Overview

The build/v1 page implements a sophisticated AI agent chat interface with real-time streaming, agent activity tracking, artifact/file management, and web app preview capabilities. The architecture follows a 2-panel layout (chat + output) with session-based state management using Zustand.

---

## 1. AI Message Rendering

### Components

**Primary Component: `AIMessageWithTools`** ([AIMessageWithTools.tsx](web/src/app/build/components/AIMessageWithTools.tsx))
- Renders AI messages with two sections:
  1. **Agent Timeline** - Visual representation of agent activities (tool calls, thinking, plans)
  2. **Message Content** - The actual text response from the agent

**Key Features:**
- Detects streaming state with "Working..." vs "Thinking..." indicators
- Displays loading spinner when content is still streaming
- Separates event messages (metadata) from display messages (content)
- Uses `MinimalMarkdown` component for text rendering

### Markdown Rendering

**Component: `MinimalMarkdown`** ([MinimalMarkdown.tsx](web/src/components/chat/MinimalMarkdown.tsx))
- Built on `react-markdown` with custom plugins
- Supports:
  - **GitHub Flavored Markdown (GFM)** - via `remark-gfm`
  - **Math expressions** - via `remark-math` and `rehype-katex` (KaTeX)
  - **Syntax highlighting** - via `rehype-highlight`
  - **Custom link handling** - uses `transformLinkUri` utility
  - **Code blocks** - via custom `CodeBlock` component with copy-to-clipboard

**Configuration:**
```typescript
rehypePlugins: [rehypeHighlight, rehypeKatex]
remarkPlugins: [remarkGfm, [remarkMath, { singleDollarTextMath: false }]]
```

**Components Overrides:**
- Custom paragraph (`MemoizedParagraph`)
- Custom links (`MemoizedLink`)
- Custom code blocks (`CodeBlock`)

### Message Display Flow

```
BuildMessageList
  ├─ Separates displayMessages (user/assistant with content)
  ├─ Separates eventMessages (assistant with message_metadata only)
  ├─ For each message:
  │  ├─ User messages → UserMessage component (right-aligned bubble)
  │  └─ Assistant messages → AIMessageWithTools
  │     └─ If last message + has events → pass eventMessages to timeline
  └─ Auto-scrolls to bottom on new messages
```

### Message Structure

```typescript
// BuildMessage interface
{
  id: string;
  type: "user" | "assistant" | "system";
  content: string;           // The text content (empty for event messages)
  timestamp: Date;
  message_metadata?: Record<string, any>;  // ACP event data (tool calls, thinking, etc.)
  toolCalls?: ToolCall[];    // Associated tool calls (populated during streaming)
}
```

---

## 2. Packet Handling & Real-Time Communication

### Transport Protocol

**Mechanism:** Server-Sent Events (SSE)
- **Endpoint:** `POST /api/build/sessions/{sessionId}/send-message`
- **Handler:** `useBuildStreaming` hook
- **Processing:** `processSSEStream` in [apiServices.ts](web/src/app/build/services/apiServices.ts)

### SSE Stream Processing

**Function:** `processSSEStream(response: Response, onPacket: Callback)`

**Parsing Logic:**
```typescript
// SSE format parsing:
// event: message
// data: { "type": "agent_message_chunk", ... }

// The backend sends:
// - event: "message" for all events (generic)
// - data.type: specific packet type (actual classification)
// - Fallback: use SSE event type if data.type is missing
```

### ACP (Agent Computation Protocol) Packets

These are raw packets sent directly from the backend's ACP system:

#### 1. **Agent Message Chunk** (`agent_message_chunk`)
```typescript
{
  type: "agent_message_chunk";
  content: ContentBlock;          // Text or image block
  timestamp: string;
  session_update?: string;
}
```
- **Handler:** Accumulates delta text and updates the assistant message
- **Note:** Arrives as deltas, must be accumulated into full content

#### 2. **Agent Thought Chunk** (`agent_thought_chunk`)
```typescript
{
  type: "agent_thought_chunk";
  content: ContentBlock;          // Internal reasoning text
  timestamp: string;
}
```
- **Handler:** Appended as a message with message_metadata
- **Display:** Shown in agent timeline (collapsible)

#### 3. **Tool Call Start** (`tool_call_start`)
```typescript
{
  type: "tool_call_start";
  tool_call_id: string;
  kind: string | null;            // e.g., "bash", "write", "read"
  title: string | null;           // Human-readable description
  content: ContentBlock | null;   // Description block
  locations: string[] | null;     // Relevant file paths
  raw_input: Record<string, any> | null;    // Command/parameters
  raw_output: Record<string, any> | null;   // (future) output
  status: string | null;
  timestamp: string;
}
```
- **Handler:** Creates `ToolCall` object with `status: "in_progress"`
- **Storage:** Added to session's `toolCalls` array

#### 4. **Tool Call Progress** (`tool_call_progress`)
```typescript
{
  type: "tool_call_progress";
  tool_call_id: string;
  kind: string | null;
  title: string | null;
  status: "pending" | "in_progress" | "completed" | "failed" | "cancelled";
  raw_input: Record<string, any> | null;
  raw_output: Record<string, any> | null;
  content: ContentBlock | null;
  timestamp: string;
}
```
- **Handler:** Updates existing tool call's status and outputs
- **Special:** Sets `finishedAt` timestamp when status is terminal

#### 5. **Agent Plan Update** (`agent_plan_update`)
```typescript
{
  type: "agent_plan_update";
  entries: Array<{
    id: string;
    description: string;
    status: "pending" | "in_progress" | "completed" | "cancelled";
    priority: string | number | null;
  }> | null;
  timestamp: string;
}
```
- **Handler:** Appended as message with metadata
- **Display:** Shown in agent timeline as collapsible section

#### 6. **Current Mode Update** (`current_mode_update`)
```typescript
{
  type: "current_mode_update";
  current_mode_id: string | null;
  timestamp: string;
}
```
- **Handler:** Logged but not currently displayed in UI

#### 7. **Prompt Response** (`prompt_response`)
```typescript
{
  type: "prompt_response";
  stop_reason: string | null;   // "end_turn", "max_tokens", etc.
}
```
- **Handler:** Sets session status to `"completed"`
- **Indicates:** Agent has finished processing

#### 8. **Error** (`error`)
```typescript
{
  type: "error";
  code: string | null;
  message: string;
  data: Record<string, any> | null;
  timestamp: string;
}
```
- **Handler:** Sets session status to `"failed"` with error message
- **Display:** Error shown in UI state

### Custom Onyx Packets (Optional, Legacy)

The system also supports these custom packet types (less common):
- `step_start` / `step_delta` / `step_end` - Step tracking
- `tool_start` / `tool_progress` / `tool_end` - Alternative tool tracking
- `output_start` / `output_delta` / `output_end` - Output chunking
- `plan` - Plan information
- `mode_update` - Mode changes
- `done` - Completion signal
- `error` - Error reporting
- `file_write` - File write tracking
- `artifact_created` - Artifact creation
- `permission_request` / `permission_response` - Permissions

### Stream Lifecycle

```typescript
// useBuildStreaming hook manages:
1. Abort previous stream if exists
2. Create new AbortController and set in store
3. Create placeholder assistant message
4. Call sendMessageStream() to get Response
5. Process SSE stream with processSSEStream()
6. Handle each packet:
   - Update store state
   - Handle special logic (accumulate text, create tool calls, etc.)
7. On error/abort: set session status to "failed"
8. Finally: reset abort controller
```

---

## 3. Tool Call Rendering (Non-Message Packets)

### Components

**Primary: `BuildAgentTimeline`** ([BuildAgentTimeline.tsx](web/src/app/build/components/BuildAgentTimeline.tsx))
- Displays all agent activities in chronological order
- Collapsible header showing summary: "X tools, Y thinking steps, Z plan updates"
- Renders different types:
  1. Tool calls (tool_call_start/progress) → `BuildToolCallRenderer`
  2. Thinking steps (agent_thought_chunk) → `BuildToolCallRenderer` (with kind: "thought")
  3. Plan updates (agent_plan_update) → `BuildToolCallRenderer` (with kind: "plan")

**Renderer: `BuildToolCallRenderer`** ([BuildToolCallRenderer.tsx](web/src/app/build/components/renderers/BuildToolCallRenderer.tsx))
- Renders individual tool calls with metadata
- Extracts information from ACP packet metadata:
  - **Icon:** Based on tool `kind` (bash, write, read, edit, thought)
  - **Status:** Visual indicator (pending, in_progress, completed, failed)
  - **Title:** Human-readable name
  - **Command:** Extracted from `raw_input` (file paths, commands, etc.)
  - **Error:** Displayed if tool failed

**Visual Structure:**
```
┌─────────────────────────────────┐
│ Agent Activity  1 tool, 2 thinking, 1 plan ⌄ │
├─────────────────────────────────┤
│ ⚙ Write File         (status icon)         │
│   /path/to/file.ts                        │
│                                            │
│ ⌗ Thinking           (status icon)         │
│   Agent is considering...                  │
│                                            │
│ 📋 Plan Update       (status icon)         │
│   3 items planned                          │
└─────────────────────────────────┘
```

### Tool Call Metadata Extraction

```typescript
// From tool_call_start/progress packet:
{
  kind: "bash" | "write" | "read" | "edit" | "other";
  title: string;                          // "Write /src/app.ts"
  raw_input: {
    command?: string;                     // For bash: "npm run build"
    file_path?: string;                   // For write/read: "/path/to/file"
    path?: string;                        // Alternative path field
    pattern?: string;                     // For grep: search pattern
  };
  status: "pending" | "in_progress" | "completed" | "failed";
  raw_output?: any;                       // Command output (if complete)
  error?: string;                         // Error message if failed
}
```

### Icon Mapping

| Tool Kind | Icon | Description |
|-----------|------|-------------|
| bash, execute | Terminal | Shell commands |
| write, edit | Edit | File operations |
| read | File Text | Reading files |
| thought, thinking | Thought Bubble | Agent reasoning |
| plan | Settings | Planning |
| other | Settings | Default |

### Status Display

| Status | Icon | Color | Animation |
|--------|------|-------|-----------|
| pending | Settings | Gray | None |
| in_progress | Spinner | Blue | Spinning |
| completed | Check | Green | None |
| failed | X | Red | None |
| cancelled | X | Gray | None |

---

## 4. Web App Retrieval & Rendering

### Components

**Primary: `PreviewTab` in `OutputPanel`** ([OutputPanel.tsx](web/src/app/build/components/OutputPanel.tsx))
- Renders iframe with webapp content
- Shows "No preview available" if no webapp

### Webapp URL Resolution

**Flow:**
```
1. On artifact_created packet with type: "nextjs_app" | "web_app"
   ↓
2. useBuildStreaming calls fetchSession()
   ↓
3. Backend returns: ApiSessionResponse with sandbox?.nextjs_port
   ↓
4. Store sets: webappUrl = `http://localhost:{port}`
   ↓
5. OutputPanel reads webappUrl from session state
   ↓
6. Renders iframe src={webappUrl}
```

### Webapp Info Endpoint

**API:** `GET /api/build/sessions/{sessionId}/webapp`
- Returns: `ApiWebappInfoResponse`
```typescript
{
  has_webapp: boolean;
  webapp_url: string | null;
  status: string;
}
```

**Polling:** `useSWR` with 5-second refresh interval
```typescript
const { data: webappInfo } = useSWR(
  shouldFetchWebapp ? `/api/build/sessions/${session.id}/webapp` : null,
  () => (session?.id ? fetchWebappInfo(session.id) : null),
  {
    refreshInterval: 5000,
    revalidateOnFocus: true,
  }
);
```

### Iframe Sandbox Settings

```typescript
<iframe
  src={webappUrl}
  className="w-full h-full rounded-08 border border-border-01 bg-white"
  sandbox="allow-scripts allow-same-origin allow-forms"
  title="Web App Preview"
/>
```

**Allowed:** Scripts, same-origin, forms
**Blocked:** Everything else (safer sandbox)

### Open Button

- Allows opening webapp in new tab: `<a href={webappUrl} target="_blank">`
- Useful for bypassing iframe limitations

---

## 5. File Directory Retrieval & Rendering

### Components

**Primary: `FilesTab` in `OutputPanel`**
- Browse the sandbox filesystem
- Navigate directories
- Download/preview files

**Advanced: `FileBrowser`** ([FileBrowser.tsx](web/src/app/build/components/FileBrowser.tsx))
- Recursive directory tree
- Expandable/collapsible folders
- File preview modal
- Download links

### Directory Listing API

**Endpoint:** `GET /api/build/sessions/{sessionId}/files?path={path}`

**Returns:**
```typescript
{
  path: string;
  entries: FileSystemEntry[];
}

// FileSystemEntry:
{
  name: string;
  path: string;
  is_directory: boolean;
  size: number | null;
  mime_type: string | null;
}
```

### File Fetching Pattern

```typescript
// FilesTab approach (simple list):
const { data: listing } = useSWR(
  `/api/build/sessions/${sessionId}/files?path=${currentPath}`,
  () => fetchDirectoryListing(sessionId, currentPath)
);

// FileBrowser approach (recursive tree):
const loadChildren = async () => {
  const listing = await listDirectory(sessionId, entry.path);
  setChildren(listing.entries);
};
```

### File Navigation

- **Breadcrumb:** Display current path
- **Back button:** Navigate to parent directory
- **Click on folder:** Navigate into directory
- **Prevent clicks on files:** Files aren't clickable (unless preview)

### File Preview

**Previewable Types:**
```typescript
// Text-based:
- text/* (any text file)
- application/json
- .md, .txt, .js, .ts, .tsx, .jsx, .css, .html, .py, .yaml, .yml

// Image-based:
- image/*
```

**Modal Component:** `FilePreviewModal` displays file content in modal

### File Download

**Pattern:**
```typescript
// Direct link download:
<a href={getArtifactUrl(sessionId, entry.path)} download={entry.name}>
  <Button>Download</Button>
</a>

// API endpoint: /api/build/sessions/{sessionId}/artifacts/{path}
```

### Directory Tree Rendering

```
📂 Workspace Files
├─ 📂 src (expandable)
│  ├─ 📄 index.ts
│  └─ 📂 components
│     └─ 📄 Button.tsx
├─ 📄 package.json
└─ 📄 README.md
```

---

## 6. Artifact Retrieval & Rendering

### Components

**Primary: `ArtifactsTab` in `OutputPanel`**
- Lists web app artifacts
- Shows "Next.js Application" subtitle
- Download button for each artifact

### Artifact Types

```typescript
type ArtifactType =
  | "nextjs_app"      // Next.js web applications (primary)
  | "web_app"         // Generic web apps
  | "pptx"            // PowerPoint presentations
  | "xlsx"            // Excel spreadsheets
  | "docx"            // Word documents
  | "markdown"        // Markdown files
  | "chart"           // Chart data/SVG
  | "csv"             // CSV files
  | "image";          // Image files
```

### Artifact Storage

```typescript
// Artifact interface:
{
  id: string;
  session_id: string;
  type: ArtifactType;
  name: string;                    // User-friendly name
  path: string;                    // File path on disk
  preview_url?: string | null;     // For web apps
  created_at: Date;
  updated_at: Date;
}
```

### Artifact Fetching

**API:** `GET /api/build/sessions/{sessionId}/artifacts`

```typescript
// Returns array of artifacts (not wrapped)
const artifacts = await fetchArtifacts(sessionId);

// Polling in OutputPanel:
const { data: polledArtifacts } = useSWR(
  shouldFetchArtifacts ? `/api/build/sessions/${sessionId}/artifacts` : null,
  () => (session?.id ? fetchArtifacts(session.id) : null),
  {
    refreshInterval: 5000,        // Poll every 5 seconds
    revalidateOnFocus: true,
  }
);

// Fall back to session store artifacts if no polled data
const artifacts = polledArtifacts ?? session?.artifacts ?? [];
```

### Artifact Creation Packet

When backend creates an artifact, it sends:

```typescript
{
  type: "artifact_created";
  artifact: {
    id: string;
    type: BackendArtifactType;   // "web_app", "markdown", etc.
    name: string;
    path: string;
    preview_url?: string;
    download_url?: string;
    mime_type?: string;
    size_bytes?: number;
  };
  timestamp: string;
}
```

**Handler Logic:**
```typescript
case "artifact_created": {
  // 1. Convert to frontend type
  const newArtifact: Artifact = {
    id: artPacket.artifact.id,
    type: artPacket.artifact.type as ArtifactType,
    ...
  };

  // 2. Add to store
  addArtifactToSession(sessionId, newArtifact);

  // 3. If webapp: fetch sandbox port to get webapp URL
  if (isWebapp) {
    const session = await fetchSession(sessionId);
    if (session.sandbox?.nextjs_port) {
      webappUrl = `http://localhost:${session.sandbox.nextjs_port}`;
      updateSessionData(sessionId, { webappUrl });
    }
  }
}
```

### Download Functionality

**Web App Download:**
```typescript
const handleDownload = () => {
  const downloadUrl = `/api/build/sessions/${sessionId}/webapp/download`;
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = "";  // Server sets filename
  link.click();
};
```

**File Download:**
- Uses direct `getArtifactUrl(sessionId, path)` links
- API endpoint: `/api/build/sessions/{sessionId}/artifacts/{path}`

---

## 7. Session & State Management

### Zustand Store: `useBuildSessionStore`

**Key Data Structure:**

```typescript
interface BuildSessionData {
  id: string;
  status: "idle" | "creating" | "running" | "completed" | "failed";
  messages: BuildMessage[];
  artifacts: Artifact[];
  toolCalls: ToolCall[];           // Active tool calls for current response
  error: string | null;
  webappUrl: string | null;
  abortController: AbortController;
  lastAccessed: Date;
  isLoaded: boolean;               // Whether session data has been fetched
  outputPanelOpen: boolean;        // Per-session output panel state
}

// Store state:
{
  currentSessionId: string | null;
  sessions: Map<string, BuildSessionData>;
  sessionHistory: SessionHistoryItem[];
  preProvisionedSessionId: string | null;
  preProvisioningPromise: Promise<string | null> | null;
}
```

### Key Actions

**Session Management:**
- `setCurrentSession(id)` - Switch active session
- `createSession(id)` - Create new session in store
- `createNewSession(prompt)` - API call + store creation
- `loadSession(id)` - Fetch from API and cache

**Current Session Shortcuts:**
- `appendMessageToCurrent(msg)` - Add message to current
- `updateLastMessageInCurrent(content)` - Update latest message
- `addArtifactToCurrent(artifact)` - Add artifact
- `setCurrentError(error)` - Set error

**Session-Specific (for streaming):**
- `appendMessageToSession(sessionId, msg)` - Immune to currentSessionId changes
- `updateLastMessageInSession(sessionId, content)` - Update specific session
- `addToolCallToSession(sessionId, toolCall)` - Add tool call
- `updateToolCallInSession(sessionId, id, updates)` - Update tool call
- `clearToolCallsInSession(sessionId)` - Clear for new response

**Abort Control:**
- `setAbortController(sessionId, controller)` - Store abort controller
- `abortSession(sessionId)` - Abort streaming

### Pre-Provisioning

**Feature:** Prepare sessions in background for faster startup

```typescript
{
  preProvisionedSessionId: string | null;
  preProvisioningPromise: Promise<string | null> | null;

  // Actions:
  ensurePreProvisionedSession() - Start pre-provisioning if needed
  consumePreProvisionedSession() - Use pre-provisioned session
}
```

**API Endpoint:** `POST /api/build/sessions/preprovision`

---

## 8. Core Data Flow

### New Session Flow

```
User submits message (with optional files)
    ↓
ChatPanel.handleSubmit()
    ↓
1. createNewSession(message) → POST /api/build/sessions/{message}
   Returns: session_id
    ↓
2. Upload files (if any) → uploadFile() for each file
    ↓
3. router.push(/build/v1?sessionId=...)
    ↓
4. useBuildSessionController detects URL change
    ↓
5. loadSession() → GET /api/build/sessions/{id}
    ↓
6. streamMessage(sessionId, message) → SSE stream starts
    ↓
Process SSE packets → update store → UI updates
```

### Existing Session Flow

```
User navigates to /build/v1?sessionId=xxx
    ↓
useBuildSessionController detects URL
    ↓
Session cached?
  Yes → setCurrentSession(id) [instant]
  No → loadSession(id) → fetch from API
    ↓
User submits message
    ↓
streamMessage(sessionId, content) → SSE stream
    ↓
Process packets → update store → UI updates
```

### Streaming Flow

```
streamMessage(sessionId, content)
    ↓
1. Abort any previous stream
2. Create new AbortController
3. Create placeholder assistant message
4. sendMessageStream() → POST with content
5. processSSEStream() → parse SSE
    ↓
For each packet:
    ├─ agent_message_chunk → accumulate + update last message
    ├─ agent_thought_chunk → append event message
    ├─ tool_call_start → create tool call
    ├─ tool_call_progress → update tool call
    ├─ agent_plan_update → append event message
    ├─ artifact_created → add artifact + fetch webapp URL
    ├─ prompt_response → set status to "completed"
    └─ error → set status to "failed"
    ↓
Store updates trigger re-renders
```

---

## 9. Key Hooks

### `useBuildSessionController`
- Manages session lifecycle based on URL
- Loads sessions from API when needed
- Aborts streams when navigating away
- Provides: `currentSessionId`, `isLoading`, `isStreaming`, `navigateToSession()`, `navigateToNewBuild()`

### `useBuildStreaming`
- Handles message streaming and packet processing
- Updates store state as packets arrive
- Manages AbortController
- Provides: `streamMessage(sessionId, content)`, `abortStream()`

### `useBuildSessionStore`
- Global Zustand store
- Session CRUD operations
- Session history management
- Pre-provisioning

---

## 10. Layout & Component Hierarchy

```
/build/v1/layout.tsx (BuildProvider + UploadFilesProvider)
├─ BuildSidebar (left panel - history, new build)
└─ page.tsx (flex row, responsive 2-panel)
   ├─ ChatPanel (left, 50% or 100%)
   │  ├─ Header (logo, output panel toggle)
   │  ├─ BuildWelcome OR BuildMessageList
   │  │  ├─ Messages (user + assistant)
   │  │  └─ Auto-scroll anchor
   │  └─ InputBar
   │
   └─ OutputPanel (right, 50% or hidden)
      ├─ Tab buttons (Preview, Files, Artifacts)
      └─ Tab content:
         ├─ PreviewTab (iframe + open button)
         ├─ FilesTab (directory browser)
         └─ ArtifactsTab (webapp list + download)
```

---

## 11. Summary Table

| Aspect | Implementation |
|--------|-----------------|
| **Message Rendering** | `MinimalMarkdown` (react-markdown + plugins) with code highlighting and KaTeX math |
| **Streaming Transport** | Server-Sent Events (SSE) via `sendMessageStream()` |
| **Packet Types** | ACP protocol: agent_message_chunk, tool_call_start/progress, agent_thought_chunk, agent_plan_update, artifact_created, error, etc. |
| **Tool Display** | `BuildAgentTimeline` → `BuildToolCallRenderer` with icons, status, commands |
| **Webapp Preview** | iframe with sandbox, polled endpoint, localhost port from session |
| **File Browser** | Recursive tree with lazy loading, preview modal, download links |
| **Artifacts** | Polled API endpoint (5s), types include nextjs_app, web_app, images, docs |
| **State Management** | Zustand store with session maps, per-session tool calls, artifacts |
| **Session Lifecycle** | Create → Load → Stream → Display, with abort support |

---

## Key Files Reference

| Component | File Path |
|-----------|-----------|
| Main Page | [web/src/app/build/v1/page.tsx](web/src/app/build/v1/page.tsx) |
| Layout | [web/src/app/build/v1/layout.tsx](web/src/app/build/v1/layout.tsx) |
| Chat Panel | [web/src/app/build/components/ChatPanel.tsx](web/src/app/build/components/ChatPanel.tsx) |
| Output Panel | [web/src/app/build/components/OutputPanel.tsx](web/src/app/build/components/OutputPanel.tsx) |
| AI Message | [web/src/app/build/components/AIMessageWithTools.tsx](web/src/app/build/components/AIMessageWithTools.tsx) |
| Agent Timeline | [web/src/app/build/components/BuildAgentTimeline.tsx](web/src/app/build/components/BuildAgentTimeline.tsx) |
| Tool Renderer | [web/src/app/build/components/renderers/BuildToolCallRenderer.tsx](web/src/app/build/components/renderers/BuildToolCallRenderer.tsx) |
| Markdown | [web/src/components/chat/MinimalMarkdown.tsx](web/src/components/chat/MinimalMarkdown.tsx) |
| Session Store | [web/src/app/build/stores/buildSessionStore.ts](web/src/app/build/stores/buildSessionStore.ts) |
| Streaming Hook | [web/src/app/build/hooks/useBuildStreaming.ts](web/src/app/build/hooks/useBuildStreaming.ts) |
| Session Controller | [web/src/app/build/hooks/useBuildSessionController.ts](web/src/app/build/hooks/useBuildSessionController.ts) |
| API Services | [web/src/app/build/services/apiServices.ts](web/src/app/build/services/apiServices.ts) |
| File Browser | [web/src/app/build/components/FileBrowser.tsx](web/src/app/build/components/FileBrowser.tsx) |
| Types | [web/src/app/build/types/index.ts](web/src/app/build/types/index.ts) |
